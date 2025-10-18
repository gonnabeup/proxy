import logging
from aiogram import Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from db.models import User, Mode, Schedule

logger = logging.getLogger(__name__)

# Глобальная ссылка на прокси-сервер для точечных перезагрузок портов
_proxy_server = None

def _set_proxy_server(server):
    global _proxy_server
    _proxy_server = server

async def cmd_admin_help(message: types.Message):
    """Обработчик команды /admin_help"""
    help_text = (
        "Административные команды:\n\n"
        "/admin_help - Показать эту справку\n"
        "/users - Показать список пользователей\n"
        "/stats - Показать статистику системы\n"
        "/payments - Заявки на оплату\n"
        "/extendsub - Продлить подписку пользователю на 1 месяц"
    )
    await message.answer(help_text)

async def cmd_users(message: types.Message):
    """Обработчик команды /users"""
    # Получаем сессию БД
    from db.models import init_db, get_session, UserRole
    engine = init_db()
    db_session = get_session(engine)
    
    try:
        # Проверка прав администратора
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not user or (user.role != UserRole.ADMIN and user.role != UserRole.SUPERADMIN):
            await message.answer("У вас нет прав для выполнения этой команды.")
            return
        
        users = db_session.query(User).all()
        
        if not users:
            await message.answer("Пользователи не найдены.")
            return
        
        response = "Список пользователей:\n\n"
        for i, user in enumerate(users, 1):
            response += f"{i}. ID: {user.id}, TG: {user.tg_id}, Логин: {user.login}, Роль: {user.role.value}\n"
            response += f"   Порт: {user.port}, Подписка до: {user.subscription_until.strftime('%d.%m.%Y')}\n\n"
        
        await message.answer(response)
    finally:
        db_session.close()

async def cmd_stats(message: types.Message):
    """Обработчик команды /stats"""
    # Получаем сессию БД
    from db.models import init_db, get_session, UserRole
    engine = init_db()
    db_session = get_session(engine)
    
    try:
        # Проверка прав администратора
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not user or (user.role != UserRole.ADMIN and user.role != UserRole.SUPERADMIN):
            await message.answer("У вас нет прав для выполнения этой команды.")
            return
        
        users_count = db_session.query(User).count()
        modes_count = db_session.query(Mode).count()
        schedules_count = db_session.query(Schedule).count()
        
        response = "Статистика системы:\n\n"
        response += f"Пользователей: {users_count}\n"
        response += f"Режимов: {modes_count}\n"
        response += f"Расписаний: {schedules_count}\n"
        
        await message.answer(response)
    finally:
        db_session.close()

def _split_args(text: str):
    try:
        parts = (text or "").strip().split()
        # отбрасываем саму команду
        if parts and parts[0].startswith('/'):
            parts = parts[1:]
        return parts
    except Exception:
        return []

async def cmd_listusers(message: types.Message):
    """Алиас для /users"""
    await cmd_users(message)

async def cmd_freerange(message: types.Message):
    """Показать свободные порты в DEFAULT_PORT_RANGE"""
    from db.models import init_db, get_session, User
    from config.settings import DEFAULT_PORT_RANGE
    engine = init_db()
    db_session = get_session(engine)
    try:
        start, end = DEFAULT_PORT_RANGE
        used = {u.port for u in db_session.query(User).all()}
        free = [p for p in range(start, end + 1) if p not in used]
        if not free:
            await message.answer("Свободных портов нет в заданном диапазоне.")
            return
        # ограничим вывод, чтобы не заспамить чат
        preview = free[:100]
        tail = "" if len(free) <= 100 else f" … и ещё {len(free)-100}"
        await message.answer("Свободные порты:\n" + ", ".join(map(str, preview)) + tail)
    finally:
        db_session.close()

async def cmd_setport(message: types.Message):
    """Назначить порт пользователю: /setport <tg_id> <port>"""
    from db.models import init_db, get_session, User, UserRole
    from config.settings import DEFAULT_PORT_RANGE
    engine = init_db()
    db_session = get_session(engine)
    try:
        # проверка прав
        admin = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not admin or admin.role not in (UserRole.ADMIN, UserRole.SUPERADMIN):
            await message.answer("У вас нет прав для выполнения этой команды.")
            return

        args = _split_args(message.text)
        if len(args) != 2:
            await message.answer("Использование: /setport tg_id port\nНапример: /setport 1146015328 4100")
            return
        try:
            tg_id = int(args[0])
            new_port = int(args[1])
        except ValueError:
            await message.answer("tg_id и port должны быть числами.")
            return
        start, end = DEFAULT_PORT_RANGE
        if not (start <= new_port <= end):
            await message.answer(f"Порт вне диапазона {start}-{end}.")
            return
        # проверка занятости порта
        if db_session.query(User).filter(User.port == new_port).first():
            await message.answer("Порт уже занят другим пользователем.")
            return
        user = db_session.query(User).filter(User.tg_id == tg_id).first()
        if not user:
            await message.answer("Пользователь с таким tg_id не найден.")
            return
        old_port = user.port
        user.port = new_port
        db_session.commit()
        await message.answer(f"Порт пользователя {user.username or tg_id} изменён: {old_port} → {new_port}.")
        # Если доступен прокси-сервер, выполняем точечные перезагрузки старого и нового портов
        try:
            if _proxy_server:
                # Останавливаем и очищаем старый порт (если был запущен)
                await _proxy_server.reload_port(old_port)
                # Запускаем новый порт
                await _proxy_server.reload_port(new_port)
                await message.answer(f"Прокси перезагружен для портов {old_port} и {new_port}.")
            else:
                await message.answer("Предупреждение: объект прокси-сервера недоступен для перезагрузки. Перезапустите сервис.")
        except Exception as e:
            logger.error(f"Ошибка перезагрузки портов {old_port}/{new_port}: {e}")
            await message.answer("Ошибка перезагрузки портов. Проверьте логи сервера.")
    finally:
        db_session.close()

async def cmd_setsub(message: types.Message):
    """Установить дату подписки: /setsub <tg_id> <DD.MM.YYYY>"""
    import datetime
    from db.models import init_db, get_session, User, UserRole
    engine = init_db()
    db_session = get_session(engine)
    try:
        admin = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not admin or admin.role not in (UserRole.ADMIN, UserRole.SUPERADMIN):
            await message.answer("У вас нет прав для выполнения этой команды.")
            return
        args = _split_args(message.text)
        if len(args) != 2:
            await message.answer("Использование: /setsub tg_id DD.MM.YYYY\nНапример: /setsub 1146015328 31.12.2025")
            return
        try:
            tg_id = int(args[0])
            until = datetime.datetime.strptime(args[1], "%d.%m.%Y")
            # выставим конец дня, чтобы дата была включительно
            until = until.replace(hour=23, minute=59, second=59)
        except Exception:
            await message.answer("Неверный формат. Ожидается дата в формате DD.MM.YYYY.")
            return
        user = db_session.query(User).filter(User.tg_id == tg_id).first()
        if not user:
            await message.answer("Пользователь с таким tg_id не найден.")
            return
        user.subscription_until = until
        db_session.commit()
        await message.answer(f"Подписка пользователя {user.username or tg_id} установлена до {until.strftime('%d.%m.%Y')}.")
    finally:
        db_session.close()

async def cmd_adduser(message: types.Message):
    """Добавить пользователя: /adduser <tg_id> <username> <port> <login>"""
    import datetime
    from db.models import init_db, get_session, User, UserRole
    from db.models import Mode
    from config.settings import DEFAULT_PORT_RANGE
    engine = init_db()
    db_session = get_session(engine)
    try:
        admin = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not admin or admin.role not in (UserRole.ADMIN, UserRole.SUPERADMIN):
            await message.answer("У вас нет прав для выполнения этой команды.")
            return
        args = _split_args(message.text)
        if len(args) < 4:
            await message.answer("Использование: /adduser tg_id username port login\nНапример: /adduser 1146015328 Ivan 4100 ivan_worker")
            return
        try:
            tg_id = int(args[0])
            username = args[1]
            port = int(args[2])
            login = args[3]
        except Exception:
            await message.answer("Неверные аргументы. Проверьте формат.")
            return
        start, end = DEFAULT_PORT_RANGE
        if not (start <= port <= end):
            await message.answer(f"Порт вне диапазона {start}-{end}.")
            return
        if db_session.query(User).filter((User.tg_id == tg_id) | (User.port == port)).first():
            await message.answer("Пользователь с таким tg_id или порт уже существует.")
            return
        user = User(
            tg_id=tg_id,
            username=username,
            role=UserRole.USER,
            port=port,
            login=login,
            timezone='UTC',
            subscription_until=datetime.datetime.now() + datetime.timedelta(days=30)
        )
        db_session.add(user)
        # Получим user.id без полного коммита
        db_session.flush()

        # Добавляем режим Sleep по умолчанию и делаем его активным
        sleep_mode = Mode(
            user_id=user.id,
            name='Sleep',
            host='sleep',
            port=0,
            alias='sleep',
            is_active=1
        )
        db_session.add(sleep_mode)
        db_session.commit()
        await message.answer(f"Пользователь добавлен: {username} (tg_id={tg_id}), порт {port}, логин {login}. По умолчанию активен режим Sleep.")
        # Сразу перезагрузим порт для нового пользователя, если доступен объект сервера
        try:
            if _proxy_server:
                await _proxy_server.reload_port(port)
                await message.answer(f"Порт {port} перезагружен для нового пользователя.")
            else:
                await message.answer("Предупреждение: объект прокси-сервера недоступен для перезагрузки. Перезапустите сервис.")
        except Exception as e:
            logger.error(f"Ошибка перезагрузки порта {port} после добавления пользователя: {e}")
            await message.answer("Ошибка перезагрузки порта. Проверьте логи сервера.")
    finally:
        db_session.close()

async def cmd_payments(message: types.Message):
    """Показать заявки на оплату со статусом PENDING"""
    from db.models import init_db, get_session, User, UserRole, PaymentRequest, PaymentStatus
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    engine = init_db()
    db_session = get_session(engine)
    try:
        admin = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not admin or admin.role not in (UserRole.ADMIN, UserRole.SUPERADMIN):
            await message.answer("У вас нет прав для выполнения этой команды.")
            return

        requests = db_session.query(PaymentRequest).filter(PaymentRequest.status == PaymentStatus.PENDING).order_by(PaymentRequest.created_at.asc()).all()
        if not requests:
            await message.answer("Нет заявок на оплату.")
            return

        await message.answer(f"Найдено заявок: {len(requests)}")
        for pr in requests:
            user = db_session.query(User).filter(User.id == pr.user_id).first()
            info = (
                f"Заявка #{pr.id}\n"
                f"Пользователь: {user.username or user.tg_id} (tg_id={user.tg_id})\n"
                f"Метод: {pr.method.value}\n"
                f"Создано: {pr.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Смотреть скрин", callback_data=f"pay_view_{pr.id}")],
                [InlineKeyboardButton(text="Одобрить", callback_data=f"pay_approve_{pr.id}"), InlineKeyboardButton(text="Отклонить", callback_data=f"pay_reject_{pr.id}")],
            ])
            await message.answer(info, reply_markup=kb)
    finally:
        db_session.close()

async def process_pay_view(callback: types.CallbackQuery):
    from db.models import init_db, get_session, PaymentRequest
    engine = init_db()
    db_session = get_session(engine)
    try:
        req_id = int(callback.data.split("_")[-1])
        pr = db_session.query(PaymentRequest).filter(PaymentRequest.id == req_id).first()
        if not pr:
            await callback.message.answer("Заявка не найдена.")
            await callback.answer()
            return
        # Показать фото оплаты
        await callback.message.answer_photo(photo=pr.file_id, caption=f"Заявка #{pr.id} от пользователя {pr.user_id}")
    except Exception:
        await callback.message.answer("Не удалось показать скрин.")
    finally:
        await callback.answer()
        db_session.close()

async def process_pay_approve(callback: types.CallbackQuery):
    from db.models import init_db, get_session, PaymentRequest, PaymentStatus, User
    engine = init_db()
    db_session = get_session(engine)
    try:
        req_id = int(callback.data.split("_")[-1])
        pr = db_session.query(PaymentRequest).filter(PaymentRequest.id == req_id).first()
        if not pr:
            await callback.message.answer("Заявка не найдена.")
            await callback.answer()
            return
        pr.status = PaymentStatus.APPROVED
        db_session.commit()
        await callback.message.answer(f"Заявка #{req_id} подтверждена.")
        try:
            user = db_session.query(User).filter(User.id == pr.user_id).first()
            if user:
                await callback.bot.send_message(chat_id=user.tg_id, text="✅ Ваша оплата подтверждена. Администратор продлит подписку в ближайшее время.")
        except Exception:
            pass
    except Exception:
        await callback.message.answer("Ошибка подтверждения заявки.")
    finally:
        await callback.answer()
        db_session.close()

async def process_pay_reject(callback: types.CallbackQuery):
    from db.models import init_db, get_session, PaymentRequest, PaymentStatus, User
    engine = init_db()
    db_session = get_session(engine)
    try:
        req_id = int(callback.data.split("_")[-1])
        pr = db_session.query(PaymentRequest).filter(PaymentRequest.id == req_id).first()
        if not pr:
            await callback.message.answer("Заявка не найдена.")
            await callback.answer()
            return
        pr.status = PaymentStatus.REJECTED
        db_session.commit()
        await callback.message.answer(f"Заявка #{req_id} отклонена.")
        try:
            user = db_session.query(User).filter(User.id == pr.user_id).first()
            if user:
                await callback.bot.send_message(chat_id=user.tg_id, text="❌ Оплата отклонена. Проверьте реквизиты и попробуйте снова через /pay.")
        except Exception:
            pass
    except Exception:
        await callback.message.answer("Ошибка отклонения заявки.")
    finally:
        await callback.answer()
        db_session.close()

async def cmd_extendsub(message: types.Message):
    """Продлить подписку пользователю на N месяцев: /extendsub <tg_id> [months]"""
    import datetime, calendar
    from db.models import init_db, get_session, User, UserRole
    engine = init_db()
    db_session = get_session(engine)
    try:
        admin = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not admin or admin.role not in (UserRole.ADMIN, UserRole.SUPERADMIN):
            await message.answer("У вас нет прав для выполнения этой команды.")
            return

        args = _split_args(message.text)
        if len(args) < 1:
            await message.answer("Использование: /extendsub tg_id [months]\nНапример: /extendsub 1146015328 1")
            return
        try:
            tg_id = int(args[0])
            months = int(args[1]) if len(args) >= 2 else 1
        except ValueError:
            await message.answer("tg_id и months должны быть числами.")
            return

        user = db_session.query(User).filter(User.tg_id == tg_id).first()
        if not user:
            await message.answer("Пользователь с таким tg_id не найден.")
            return

        base = max(user.subscription_until, datetime.datetime.now())
        y = base.year
        m = base.month + months
        # нормализация года/месяца
        y += (m - 1) // 12
        m = ((m - 1) % 12) + 1
        d = min(base.day, calendar.monthrange(y, m)[1])
        new_until = base.replace(year=y, month=m, day=d)
        # выставим конец дня
        new_until = new_until.replace(hour=23, minute=59, second=59, microsecond=0)

        user.subscription_until = new_until
        db_session.commit()
        await message.answer(f"Подписка пользователя {user.username or tg_id} продлена до {new_until.strftime('%d.%m.%Y')}.")
    finally:
        db_session.close()

def register_admin_handlers(dp: Dispatcher):
    """Регистрация обработчиков административных команд"""
    # существующие команды
    dp.message.register(cmd_admin_help, Command("admin_help"))
    dp.message.register(cmd_users, Command("users"))
    dp.message.register(cmd_stats, Command("stats"))
    # новые команды и алиасы, соответствующие клавиатуре/README
    dp.message.register(cmd_adduser, Command("adduser"))
    dp.message.register(cmd_setsub, Command("setsub"))
    dp.message.register(cmd_setport, Command("setport"))
    dp.message.register(cmd_freerange, Command("freerange"))
    dp.message.register(cmd_listusers, Command("listusers"))
    dp.message.register(cmd_payments, Command("payments"))
    dp.message.register(cmd_extendsub, Command("extendsub"))

async def cmd_reloadport(message: types.Message):
    """Точечная перезагрузка порта: /reloadport <port>"""
    from db.models import init_db, get_session, User, UserRole
    engine = init_db()
    db_session = get_session(engine)
    try:
        admin = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not admin or admin.role not in (UserRole.ADMIN, UserRole.SUPERADMIN):
            await message.answer("У вас нет прав для выполнения этой команды.")
            return

        args = _split_args(message.text)
        if len(args) != 1:
            await message.answer("Использование: /reloadport port\nНапример: /reloadport 4202")
            return
        try:
            port = int(args[0])
        except ValueError:
            await message.answer("Порт должен быть числом.")
            return

        if not _proxy_server:
            await message.answer("Объект прокси-сервера недоступен. Перезапустите сервис.")
            return
        try:
            await _proxy_server.reload_port(port)
            await message.answer(f"Порт {port} перезагружен.")
        except Exception as e:
            logger.error(f"Ошибка перезагрузки порта {port}: {e}")
            await message.answer("Ошибка перезагрузки порта. Проверьте логи сервера.")
    finally:
        db_session.close()

def register_admin_handlers(dp: Dispatcher, proxy_server=None):
    """Регистрация обработчиков административных команд, с возможной передачей proxy_server"""
    # Устанавливаем ссылку на прокси-сервер
    if proxy_server:
        _set_proxy_server(proxy_server)

    # существующие команды
    dp.message.register(cmd_admin_help, Command("admin_help"))
    dp.message.register(cmd_users, Command("users"))
    dp.message.register(cmd_stats, Command("stats"))
    # новые команды и алиасы, соответствующие клавиатуре/README
    dp.message.register(cmd_adduser, Command("adduser"))
    dp.message.register(cmd_setsub, Command("setsub"))
    dp.message.register(cmd_setport, Command("setport"))
    dp.message.register(cmd_freerange, Command("freerange"))
    dp.message.register(cmd_listusers, Command("listusers"))
    # Точечная перезагрузка порта
    dp.message.register(cmd_reloadport, Command("reloadport"))
    # Заявки на оплату и продление
    dp.message.register(cmd_payments, Command("payments"))
    dp.message.register(cmd_extendsub, Command("extendsub"))
    # Колбэки заявок
    dp.callback_query.register(process_pay_view, F.data.startswith("pay_view_"))
    dp.callback_query.register(process_pay_approve, F.data.startswith("pay_approve_"))
    dp.callback_query.register(process_pay_reject, F.data.startswith("pay_reject_"))
