import logging
import aiohttp
from aiogram import Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from db.models import User, Mode, Schedule
from config.settings import PROXY_API_HOST, PROXY_API_PORT, PROXY_API_TOKEN, APP_API_HOST, APP_API_PORT, APP_API_TOKEN

logger = logging.getLogger(__name__)

# Глобальная ссылка на прокси-сервер для точечных перезагрузок портов
_proxy_server = None

def _set_proxy_server(server):
    global _proxy_server
    _proxy_server = server

async def _proxy_api_reload_port(port: int):
    base = f"http://{PROXY_API_HOST}:{PROXY_API_PORT}"
    url = base + "/reload-port"
    headers = {"X-Proxy-Token": PROXY_API_TOKEN} if PROXY_API_TOKEN else {}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"port": port}, headers=headers) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(f"proxy api error {resp.status}: {text}")

async def _api_get(path: str):
    base = f"http://{APP_API_HOST}:{APP_API_PORT}"
    url = base + path
    headers = {"X-Api-Token": APP_API_TOKEN} if APP_API_TOKEN else {}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(text)
            import json as _json
            return _json.loads(text)

async def _api_post(path: str, payload: dict):
    base = f"http://{APP_API_HOST}:{APP_API_PORT}"
    url = base + path
    headers = {"X-Api-Token": APP_API_TOKEN} if APP_API_TOKEN else {}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise RuntimeError(text)
            import json as _json
            return _json.loads(text)

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
    try:
        data = await _api_get("/freerange")
        free = data.get("free_ports", [])
        if not free:
            await message.answer("Свободных портов нет в заданном диапазоне.")
            return
        preview = free[:100]
        tail = "" if len(free) <= 100 else f" … и ещё {len(free)-100}"
        await message.answer("Свободные порты:\n" + ", ".join(map(str, preview)) + tail)
    except Exception:
        await message.answer("Ошибка запроса свободных портов.")

async def cmd_setport(message: types.Message):
    """Назначить порт пользователю: /setport <tg_id> <port>"""
    try:
        args = _split_args(message.text)
        if len(args) != 2:
            await message.answer("Использование: /setport tg_id port\nНапример: /setport 1146015328 4100")
            return
        tg_id = int(args[0])
        new_port = int(args[1])
        await _api_post("/admin/set-port", {"tg_id": tg_id, "port": new_port})
        await message.answer(f"Порт пользователя {tg_id} изменён на {new_port}. Прокси перезагружен.")
    except Exception:
        await message.answer("Ошибка изменения порта.")

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
    try:
        args = _split_args(message.text)
        if len(args) < 4:
            await message.answer("Использование: /adduser tg_id username port login\nНапример: /adduser 1146015328 Ivan 4100 ivan_worker")
            return
        tg_id = int(args[0])
        username = args[1]
        port = int(args[2])
        login = args[3]
        await _api_post("/admin/add-user", {"tg_id": tg_id, "username": username, "port": port, "login": login})
        await message.answer(f"Пользователь добавлен: {username} (tg_id={tg_id}), порт {port}, логин {login}.")
        try:
            if _proxy_server:
                await _proxy_server.reload_port(port)
            else:
                await _proxy_api_reload_port(port)
        except Exception:
            pass
    except Exception:
        await message.answer("Ошибка добавления пользователя.")

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
                [InlineKeyboardButton(text="Смотреть файл/скрин", callback_data=f"pay_view_{pr.id}")],
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
        caption = f"Заявка #{pr.id} от пользователя {pr.user_id}"
        try:
            await callback.message.answer_photo(photo=pr.file_id, caption=caption)
        except Exception:
            try:
                await callback.message.answer_document(document=pr.file_id, caption=caption)
            except Exception:
                await callback.message.answer("Не удалось показать файл/скрин. Возможно, файл удалён или недоступен.")
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
                await callback.bot.send_message(chat_id=user.tg_id, text="❌ Ваша оплата отклонена. Проверьте данные и попробуйте снова.")
        except Exception:
            pass
    except Exception:
        await callback.message.answer("Ошибка отклонения заявки.")
    finally:
        await callback.answer()
        db_session.close()

# Новый обработчик: скрыть уведомление у админа
async def process_pay_seen(callback: types.CallbackQuery):
    from db.models import init_db, get_session, User, UserRole, PaymentRequest
    engine = init_db()
    db_session = get_session(engine)
    try:
        admin = db_session.query(User).filter(User.tg_id == callback.from_user.id).first()
        if not admin or admin.role not in (UserRole.ADMIN, UserRole.SUPERADMIN):
            await callback.answer("Нет прав", show_alert=True)
            return
        req_id = int(callback.data.split("_")[-1])
        _ = db_session.query(PaymentRequest.id).filter(PaymentRequest.id == req_id).first()
        # Удаляем уведомление из чата админа
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_text(f"Заявка #{req_id} помечена как просмотренная.")
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
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

        try:
            if _proxy_server:
                await _proxy_server.reload_port(port)
            else:
                await _proxy_api_reload_port(port)
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
    dp.callback_query.register(process_pay_seen, F.data.startswith("pay_seen_"))
