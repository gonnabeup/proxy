import logging
import asyncio
from datetime import datetime
from aiogram import Dispatcher, types, F
 
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

from db.models import User, Mode, Schedule, get_session, init_db, UserRole
from bot.keyboards import (
    get_modes_keyboard,
    get_cancel_keyboard,
    get_yes_no_keyboard,
    get_main_keyboard,
    get_schedule_action_keyboard,
    get_schedule_list_keyboard,
    get_pool_link_keyboard,
)

logger = logging.getLogger(__name__)

# Унифицированная проверка прав администратора (Enum/строка)
def _is_admin_user(user) -> bool:
    try:
        if not user:
            return False
        role = getattr(user, "role", None)
        if role is None:
            return False
        # Если роль строка, нормализуем и сравним
        if isinstance(role, str):
            return role.upper() in ("ADMIN", "SUPERADMIN")
        # Иначе предполагаем Enum UserRole
        return role in (UserRole.ADMIN, UserRole.SUPERADMIN)
    except Exception:
        return False

# Унифицированная проверка текста отмены
def _is_cancel_text(text: str) -> bool:
    if not text:
        return False
    return text.strip().lower() in {"отмена", "cancel", "отменить", "стоп"}

# Состояния для FSM
class SetLoginState(StatesGroup):
    waiting_for_login = State()

class AddModeState(StatesGroup):
    waiting_for_name = State()
    waiting_for_host = State()
    waiting_for_port = State()
    waiting_for_alias = State()

class SetModeState(StatesGroup):
    waiting_for_mode = State()

class ScheduleState(StatesGroup):
    waiting_for_action = State()
    waiting_for_mode = State()
    waiting_for_start_time = State()
    waiting_for_end_time = State()
    waiting_for_confirmation = State()

class TimezoneState(StatesGroup):
    waiting_for_timezone_input = State()

class PaymentState(StatesGroup):
    waiting_for_screenshot = State()

async def cmd_start(message: types.Message, state: FSMContext = None):
    """Обработчик команды /start"""
    # Получаем сессию БД
    engine = init_db()
    db_session = get_session(engine)
    
    try:
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        is_admin = _is_admin_user(user)
        
        if user:
            await message.answer(
                f"Добро пожаловать, {user.username}!\n\n"
                f"Ваш порт: {user.port}\n"
                f"Ваш логин: {user.login}\n"
                f"Подписка активна до: {user.subscription_until.strftime('%d.%m.%Y')}\n\n"
                "Используйте команды для управления прокси.",
                reply_markup=get_main_keyboard(is_admin=is_admin)
            )
        else:
            await message.answer(
                "Вы не зарегистрированы в системе. Обратитесь к администратору для получения доступа."
            )
    finally:
        db_session.close()
    
    # Сбрасываем состояние FSM, если оно есть
    if state:
        await state.clear()

async def cmd_setlogin(message: types.Message, state: FSMContext):
    """Обработчик команды /setlogin"""
    await state.set_state(SetLoginState.waiting_for_login)
    await message.answer(
        "Введите новый логин для ваших воркеров:",
        reply_markup=get_cancel_keyboard()
    )

async def process_login_input(message: types.Message, state: FSMContext, db_session):
    """Обработка ввода нового логина"""
    new_login = message.text.strip()

    # Обработка отмены прямо в обработчике ввода логина
    if new_login.lower() == "отмена":
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        is_admin = _is_admin_user(user)
        await message.answer("Действие отменено.", reply_markup=get_main_keyboard(is_admin=is_admin))
        await state.clear()
        return
    
    if len(new_login) < 3 or len(new_login) > 50:
        await message.answer("Логин должен содержать от 3 до 50 символов. Попробуйте еще раз:")
        return
    
    # Обновляем логин пользователя в БД
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    if user:
        user.login = new_login
        db_session.commit()
        is_admin = _is_admin_user(user)
        await message.answer(
            f"Логин успешно изменен на: {new_login}",
            reply_markup=get_main_keyboard(is_admin=is_admin)
        )
    else:
        await message.answer("Вы не зарегистрированы в системе.")
    
    # Сбрасываем состояние FSM
    await state.clear()

async def cmd_addmode(message: types.Message, state: FSMContext):
    """Обработчик команды /addmode"""
    await state.set_state(AddModeState.waiting_for_name)
    await message.answer(
        "Введите название режима (например, 'anypossiblename123'):",
        reply_markup=get_cancel_keyboard()
    )

async def process_mode_name(message: types.Message, state: FSMContext):
    """Обработка ввода названия режима"""
    mode_name = message.text.strip()
    if _is_cancel_text(mode_name):
        # Унифицированная отмена с показом основной клавиатуры
        await cmd_cancel(message, state)
        return
    
    # Сохраняем название в состоянии
    await state.update_data(name=mode_name)
    
    # Переходим к следующему шагу
    await state.set_state(AddModeState.waiting_for_host)
    await message.answer("Введите хост пула, без указания протокола (например, пул дал 'stratum+tcp://btc.pool.com', надо ввести 'btc.pool.com'):", reply_markup=get_cancel_keyboard())

async def process_mode_host(message: types.Message, state: FSMContext):
    """Обработка ввода хоста пула"""
    mode_host = message.text.strip()
    if _is_cancel_text(mode_host):
        await cmd_cancel(message, state)
        return
    
    # Сохраняем хост в состоянии
    await state.update_data(host=mode_host)
    
    # Переходим к следующему шагу
    await state.set_state(AddModeState.waiting_for_port)
    await message.answer("Введите порт пула (например, '3333'):", reply_markup=get_cancel_keyboard())

async def process_mode_port(message: types.Message, state: FSMContext):
    """Обработка ввода порта пула"""
    try:
        text = message.text.strip()
        if _is_cancel_text(text):
            await cmd_cancel(message, state)
            return
        mode_port = int(text)
        
        # Сохраняем порт в состоянии
        await state.update_data(port=mode_port)
        
        # Переходим к следующему шагу
        await state.set_state(AddModeState.waiting_for_alias)
        await message.answer("Введите алиас для пула (например, 'poolsalias'):", reply_markup=get_cancel_keyboard())
    except ValueError:
        await message.answer("Порт должен быть числом. Попробуйте еще раз:")

async def process_mode_alias(message: types.Message, state: FSMContext, db_session):
    """Обработка ввода алиаса для пула"""
    mode_alias = message.text.strip()
    if _is_cancel_text(mode_alias):
        await cmd_cancel(message, state)
        return
    
    # Получаем все данные из состояния
    data = await state.get_data()
    name = data.get('name')
    host = data.get('host')
    port = data.get('port')
    
    # Создаем новый режим в БД
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    if user:
        new_mode = Mode(
            user_id=user.id,
            name=name,
            host=host,
            port=port,
            alias=mode_alias
        )
        db_session.add(new_mode)
        db_session.commit()
        
        is_admin = _is_admin_user(user)
        await message.answer(
            f"Режим успешно добавлен!\n\n"
            f"Название: {name}\n"
            f"Хост: {host}\n"
            f"Порт: {port}\n"
            f"Алиас: {mode_alias}",
            reply_markup=get_main_keyboard(is_admin=is_admin)
        )
    else:
        await message.answer("Вы не зарегистрированы в системе.")
    
    # Сбрасываем состояние FSM
    await state.clear()

async def cmd_modes(message: types.Message, db_session):
    """Обработчик команды /modes"""
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    
    if not user:
        await message.answer("Вы не зарегистрированы в системе.")
        return
    
    modes = db_session.query(Mode).filter(Mode.user_id == user.id).all()
    
    if not modes:
        await message.answer("У вас пока нет добавленных режимов. Используйте /addmode для добавления.")
        return
    
    response = "Ваши режимы:\n\n"
    for i, mode in enumerate(modes, 1):
        response += f"{i}. {mode.name}\n"
        response += f"   Хост: {mode.host}:{mode.port}\n"
        response += f"   Алиас: {mode.alias}\n\n"
    
    await message.answer(response)

async def cmd_setmode(message: types.Message, state: FSMContext, db_session):
    """Обработчик команды /setmode"""
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    
    if not user:
        await message.answer("Вы не зарегистрированы в системе.")
        return
    
    modes = db_session.query(Mode).filter(Mode.user_id == user.id).all()
    
    if not modes:
        await message.answer("У вас пока нет добавленных режимов. Используйте /addmode для добавления.")
        return
    
    await state.set_state(SetModeState.waiting_for_mode)
    await message.answer(
        "Выберите режим для активации:",
        reply_markup=get_modes_keyboard(modes, action="set")
    )

async def process_mode_callback(callback: types.CallbackQuery, state: FSMContext, db_session):
    """Обработка инлайн-выбора режима через callback_data"""
    data = callback.data  # ожидаем формат: set_mode_<id>
    try:
        mode_id = int(data.split("_")[-1])
        user = db_session.query(User).filter(User.tg_id == callback.from_user.id).first()
        if not user:
            await callback.message.answer("Вы не зарегистрированы в системе.")
            await callback.answer()
            return

        mode = db_session.query(Mode).filter(Mode.id == mode_id, Mode.user_id == user.id).first()
        if not mode:
            await callback.message.answer("Режим не найден. Попробуйте еще раз.")
            await callback.answer()
            return

        # Деактивируем предыдущий режим, активируем выбранный
        db_session.query(Mode).filter(Mode.user_id == user.id, Mode.is_active == 1).update({Mode.is_active: 0})
        mode.is_active = 1
        db_session.commit()

        is_admin = _is_admin_user(user)
        await callback.message.answer(
            f"Активный режим установлен: {mode.name}",
            reply_markup=get_main_keyboard(is_admin=is_admin)
        )
    except Exception:
        await callback.message.answer("Ошибка обработки выбора режима. Попробуйте снова.")
    finally:
        await callback.answer()
        await state.clear()

async def process_mode_selection(message: types.Message, state: FSMContext, db_session):
    """Обработка выбора режима"""
    try:
        text = message.text.strip()
        if _is_cancel_text(text):
            user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
            is_admin = _is_admin_user(user)
            await message.answer("Действие отменено.", reply_markup=get_main_keyboard(is_admin=is_admin))
            return
        mode_id = int(text)
        
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        mode = db_session.query(Mode).filter(Mode.id == mode_id, Mode.user_id == user.id).first()
        
        if not mode:
            await message.answer("Режим не найден. Попробуйте еще раз.")
            return
        
        # Снимаем флаг активности у предыдущего режима и активируем выбранный
        db_session.query(Mode).filter(Mode.user_id == user.id, Mode.is_active == 1).update({Mode.is_active: 0})
        mode.is_active = 1
        db_session.commit()
        
        is_admin = _is_admin_user(user)
        await message.answer(
            f"Активный режим установлен: {mode.name}",
            reply_markup=get_main_keyboard(is_admin=is_admin)
        )
    except ValueError:
        await message.answer("Пожалуйста, введите номер режима.")
    finally:
        # Сбрасываем состояние FSM
        await state.clear()

async def cmd_schedule(message: types.Message, state: FSMContext):
    """Обработчик команды /schedule"""
    await state.set_state(ScheduleState.waiting_for_action)
    await message.answer(
        "Выберите действие:\n"
        "1. Добавить расписание (add)\n"
        "2. Показать расписания (list)\n"
        "3. Удалить расписание (delete)",
        reply_markup=get_schedule_action_keyboard()
    )

async def process_schedule_action(message: types.Message, state: FSMContext, db_session):
    """Обработка выбора действия с расписанием"""
    action_text = message.text.strip()
    if _is_cancel_text(action_text):
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        is_admin = _is_admin_user(user)
        await message.answer("Действие отменено.", reply_markup=get_main_keyboard(is_admin=is_admin))
        await state.clear()
        return
    action = action_text.lower()
    
    if action in ['add', '1', 'добавить']:
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        modes = db_session.query(Mode).filter(Mode.user_id == user.id).all()
        
        if not modes:
            await message.answer("У вас пока нет добавленных режимов. Используйте /addmode для добавления.")
            await state.clear()
            return
        
        await state.set_state(ScheduleState.waiting_for_mode)
        await message.answer(
            "Выберите режим для расписания:",
            reply_markup=get_modes_keyboard(modes, action="schedule")
        )
    
    elif action in ['list', '2', 'список']:
        await show_schedules(message, db_session)
        await state.clear()
    
    elif action in ['delete', '3', 'удалить']:
        # Показ списка расписаний с кнопками удаления
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not user:
            await message.answer("Вы не зарегистрированы в системе.")
            await state.clear()
            return
        schedules = db_session.query(Schedule).filter(Schedule.user_id == user.id).all()
        if not schedules:
            await message.answer("У вас пока нет добавленных расписаний.")
            await state.clear()
            return
        await message.answer(
            "Выберите расписание для удаления:",
            reply_markup=get_schedule_list_keyboard(schedules)
        )
        # Состояние можно сбросить, удаление обработаем через callback
        await state.clear()
    
    else:
        await message.answer("Неизвестное действие. Пожалуйста, выберите из списка.")

async def process_schedule_mode(message: types.Message, state: FSMContext, db_session):
    """Обработка выбора режима для расписания"""
    try:
        mode_id = int(message.text.strip())
        
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        mode = db_session.query(Mode).filter(Mode.id == mode_id, Mode.user_id == user.id).first()
        
        if not mode:
            await message.answer("Режим не найден. Попробуйте еще раз.")
            return
        
        # Сохраняем выбранный режим в состоянии
        await state.update_data(mode_id=mode.id, mode_name=mode.name)
        
        # Переходим к следующему шагу
        await state.set_state(ScheduleState.waiting_for_start_time)
        await message.answer(
            "Введите время начала в формате ЧЧ:ММ (например, 08:30):",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("Пожалуйста, введите номер режима.")

async def process_schedule_mode_callback(callback: types.CallbackQuery, state: FSMContext, db_session):
    """Обработка выбора режима для расписания через инлайн-кнопки"""
    data = callback.data  # ожидаем формат: schedule_mode_<id>
    try:
        mode_id = int(data.split("_")[-1])
        user = db_session.query(User).filter(User.tg_id == callback.from_user.id).first()
        if not user:
            await callback.message.answer("Вы не зарегистрированы в системе.")
            await callback.answer()
            return
        mode = db_session.query(Mode).filter(Mode.id == mode_id, Mode.user_id == user.id).first()
        if not mode:
            await callback.message.answer("Режим не найден. Попробуйте еще раз.")
            await callback.answer()
            return

        # Сохраняем выбранный режим и переходим к вводу времени начала
        await state.update_data(mode_id=mode.id, mode_name=mode.name)
        await state.set_state(ScheduleState.waiting_for_start_time)
        await callback.message.answer(
            "Введите время начала в формате ЧЧ:ММ (например, 08:30):",
            reply_markup=get_cancel_keyboard()
        )
    except Exception:
        await callback.message.answer("Ошибка обработки выбора режима. Попробуйте снова.")
    finally:
        await callback.answer()

async def process_schedule_delete_callback(callback: types.CallbackQuery):
    """Удаление расписания по инлайн-кнопке delete_schedule_<id>"""
    data = callback.data  # ожидаем формат: delete_schedule_<id>
    engine = init_db()
    db_session = get_session(engine)
    try:
        schedule_id = int(data.split("_")[-1])
        schedule = db_session.query(Schedule).filter(Schedule.id == schedule_id).first()
        if not schedule:
            await callback.message.answer("Расписание не найдено.")
            await callback.answer()
            return
        user = db_session.query(User).filter(User.id == schedule.user_id).first()
        is_admin = bool(user and user.role in (UserRole.ADMIN, UserRole.SUPERADMIN))
        db_session.delete(schedule)
        db_session.commit()
        await callback.message.answer(
            "Расписание удалено.",
            reply_markup=get_main_keyboard(is_admin=is_admin)
        )
    except Exception:
        await callback.message.answer("Ошибка удаления расписания. Попробуйте снова.")
    finally:
        await callback.answer()
        db_session.close()

async def process_schedule_start_time(message: types.Message, state: FSMContext):
    """Обработка ввода времени начала расписания"""
    start_time = message.text.strip()
    if _is_cancel_text(start_time):
        await cmd_cancel(message, state)
        return
    
    # Проверяем формат времени
    try:
        datetime.strptime(start_time, "%H:%M")
        
        # Сохраняем время начала в состоянии
        await state.update_data(start_time=start_time)
        
        # Переходим к следующему шагу
        await state.set_state(ScheduleState.waiting_for_end_time)
        await message.answer("Введите время окончания в формате ЧЧ:ММ (например, 16:30):", reply_markup=get_cancel_keyboard())
    except ValueError:
        await message.answer("Неверный формат времени. Используйте формат ЧЧ:ММ (например, 08:30).")

async def process_schedule_end_time(message: types.Message, state: FSMContext):
    """Обработка ввода времени окончания расписания"""
    end_time = message.text.strip()
    if _is_cancel_text(end_time):
        await cmd_cancel(message, state)
        return
    
    # Проверяем формат времени
    try:
        datetime.strptime(end_time, "%H:%M")
        
        # Сохраняем время окончания в состоянии
        await state.update_data(end_time=end_time)
        
        # Получаем все данные из состояния для подтверждения
        data = await state.get_data()
        mode_name = data.get('mode_name')
        start_time = data.get('start_time')
        
        # Переходим к подтверждению
        await state.set_state(ScheduleState.waiting_for_confirmation)
        await message.answer(
            f"Подтвердите создание расписания:\n\n"
            f"Режим: {mode_name}\n"
            f"Время начала: {start_time}\n"
            f"Время окончания: {end_time}\n\n"
            f"Создать расписание?",
            reply_markup=get_yes_no_keyboard()
        )
    except ValueError:
        await message.answer("Неверный формат времени. Используйте формат ЧЧ:ММ (например, 16:30).")

async def process_schedule_confirmation(message: types.Message, state: FSMContext, db_session):
    """Обработка подтверждения создания расписания"""
    answer = message.text.strip().lower()
    if _is_cancel_text(answer):
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        is_admin = _is_admin_user(user)
        await message.answer("Действие отменено.", reply_markup=get_main_keyboard(is_admin=is_admin))
        await state.clear()
        return
    
    if answer in ['да', 'yes', 'y']:
        # Получаем все данные из состояния
        data = await state.get_data()
        mode_id = data.get('mode_id')
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        
        # Получаем пользователя
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        
        if user:
            # Создаем новое расписание
            new_schedule = Schedule(
                user_id=user.id,
                mode_id=mode_id,
                start_time=start_time,
                end_time=end_time
            )
            db_session.add(new_schedule)
            db_session.commit()
            
            is_admin = _is_admin_user(user)
            await message.answer(
                "Расписание успешно создано!",
                reply_markup=get_main_keyboard(is_admin=is_admin)
            )
        else:
            await message.answer("Вы не зарегистрированы в системе.")
    else:
        # Показываем основную клавиатуру после отмены
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        is_admin = _is_admin_user(user)
        await message.answer(
            "Создание расписания отменено.",
            reply_markup=get_main_keyboard(is_admin=is_admin)
        )
    
    # Сбрасываем состояние FSM
    await state.clear()

async def show_schedules(message: types.Message, db_session):
    """Показать список расписаний пользователя"""
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    
    if not user:
        await message.answer("Вы не зарегистрированы в системе.", reply_markup=get_main_keyboard(is_admin=False))
        return
    
    schedules = db_session.query(Schedule).filter(Schedule.user_id == user.id).all()
    
    if not schedules:
        is_admin = _is_admin_user(user)
        await message.answer("У вас пока нет добавленных расписаний.", reply_markup=get_main_keyboard(is_admin=is_admin))
        return
    
    response = "Ваши расписания:\n\n"
    for i, schedule in enumerate(schedules, 1):
        mode = db_session.query(Mode).filter(Mode.id == schedule.mode_id).first()
        mode_name = mode.name if mode else "Неизвестный режим"
        
        response += f"{i}. {mode_name}\n"
        response += f"   Время: {schedule.start_time} - {schedule.end_time}\n\n"
    is_admin = _is_admin_user(user)
    await message.answer(response, reply_markup=get_main_keyboard(is_admin=is_admin))

async def cmd_status(message: types.Message, db_session):
    """Обработчик команды /status"""
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    
    if not user:
        await message.answer("Вы не зарегистрированы в системе.")
        return
    
    # Определяем активный режим по флагу is_active
    active_mode = db_session.query(Mode).filter(Mode.user_id == user.id, Mode.is_active == 1).first()
    
    response = f"Ваш статус:\n\n"
    response += f"Порт: {user.port}\n"
    response += f"Логин: {user.login}\n"
    response += f"Подписка активна до: {user.subscription_until.strftime('%d.%m.%Y')}\n"
    
    if active_mode:
        response += f"\nАктивный режим: {active_mode.name}\n"
        response += f"Пул: {active_mode.host}:{active_mode.port}\n"
        response += f"Алиас: {active_mode.alias}\n"
    else:
        response += "\nАктивный режим не выбран. Используйте /setmode для выбора режима."
    
    await message.answer(response)

async def cmd_settimezone(message: types.Message, state: FSMContext):
    """Команда установки часового пояса"""
    # Предложим популярные варианты через инлайн-клавиатуру
    from bot.keyboards import get_timezone_keyboard
    await state.set_state(TimezoneState.waiting_for_timezone_input)
    await message.answer(
        "Выберите часовой пояс или введите IANA-идентификатор (например, Europe/Moscow):",
        reply_markup=get_timezone_keyboard()
    )

async def process_timezone_callback(callback: types.CallbackQuery, state: FSMContext, db_session):
    from zoneinfo import ZoneInfo
    data = callback.data  # set_timezone_<tz>
    try:
        tz = data.split("set_timezone_")[-1]
        if tz == "OTHER":
            await callback.message.answer("Введите IANA-идентификатор часового пояса (например, Europe/Moscow):")
            await state.set_state(TimezoneState.waiting_for_timezone_input)
            await callback.answer()
            return
        # Проверим валидность
        ZoneInfo(tz)
        user = db_session.query(User).filter(User.tg_id == callback.from_user.id).first()
        if not user:
            await callback.message.answer("Вы не зарегистрированы в системе.")
            await callback.answer()
            return
        user.timezone = tz
        db_session.commit()
        is_admin = _is_admin_user(user)
        await callback.message.answer(f"Часовой пояс установлен: {tz}", reply_markup=get_main_keyboard(is_admin=is_admin))
    except Exception:
        await callback.message.answer("Неверный часовой пояс. Попробуйте снова.")
    finally:
        await callback.answer()
        await state.clear()

async def process_timezone_input(message: types.Message, state: FSMContext, db_session):
    from zoneinfo import ZoneInfo
    text = message.text.strip()
    if _is_cancel_text(text):
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        is_admin = _is_admin_user(user)
        await message.answer("Действие отменено.", reply_markup=get_main_keyboard(is_admin=is_admin))
        await state.clear()
        return
    # Быстрые русские алиасы
    aliases = {
        "москва": "Europe/Moscow",
        "питер": "Europe/Moscow",
        "санкт-петербург": "Europe/Moscow",
        "новосибирск": "Asia/Novosibirsk",
        "иркутск": "Asia/Irkutsk",
        "utc": "UTC",
    }
    tz = aliases.get(text.lower(), text)
    try:
        ZoneInfo(tz)
    except Exception:
        await message.answer("Неверный часовой пояс. Введите корректный IANA идентификатор, например Europe/Moscow.")
        return
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    if not user:
        await message.answer("Вы не зарегистрированы в системе.")
        await state.clear()
        return
    user.timezone = tz
    db_session.commit()
    is_admin = _is_admin_user(user)
    await message.answer(f"Часовой пояс установлен: {tz}", reply_markup=get_main_keyboard(is_admin=is_admin))
    await state.clear()

async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    # Создаем сессию БД, чтобы получить порт и логин пользователя
    engine = init_db()
    db_session = get_session(engine)
    try:
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        # Блок команд
        commands_block = (
            "Доступные команды:\n\n"
            "/start - Начать работу с ботом\n"
            "/setlogin - Задать/изменить логин для воркеров\n"
            "/addmode - Добавить новый режим пула\n"
            "/modes - Показать список ваших режимов\n"
            "/setmode - Выбрать активный режим\n"
            "/schedule - Управление расписанием\n"
            "/status - Показать текущий статус\n"
            "/timezone - Установить часовой пояс\n"
            "/pay - Оплатить подписку\n"
            "/help - Показать эту справку\n\n"
        )
        if user:
            connection_line = f"Строка подключения: 81.30.105.170:{user.port}, воркер: {user.login}.номер, пароль: x"
            await message.answer(commands_block + connection_line)
        else:
            await message.answer(commands_block + "Вы не зарегистрированы в системе. Обратитесь к администратору.")
    finally:
        db_session.close()

async def cmd_cancel(message: types.Message, state: FSMContext):
    """Обработчик команды отмены"""
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        # Показываем основную клавиатуру после отмены
        engine = init_db()
        db_session = get_session(engine)
        try:
            user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
            is_admin = _is_admin_user(user)
            await message.answer("Действие отменено.", reply_markup=get_main_keyboard(is_admin=is_admin))
        finally:
            db_session.close()
    else:
        engine = init_db()
        db_session = get_session(engine)
        try:
            user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
            is_admin = _is_admin_user(user)
            await message.answer("Нет активного действия для отмены.", reply_markup=get_main_keyboard(is_admin=is_admin))
        finally:
            db_session.close()

# ===== Оплата подписки =====
def _payment_settings():
    try:
        from config.settings import WALLET_BEP20_ADDRESS, WALLET_TRC20_ADDRESS, CARD_NUMBER
        return {
            "bep20_addr": WALLET_BEP20_ADDRESS,
            "trc20_addr": WALLET_TRC20_ADDRESS,
            "card_number": CARD_NUMBER,
        }
    except Exception:
        return {
            "bep20_addr": "",
            "trc20_addr": "",
            "card_number": "",
        }

async def cmd_pay(message: types.Message, state: FSMContext):
    # Если уже в процессе оплаты, запрещаем повторный выбор
    current_state = await state.get_state()
    if current_state == PaymentState.waiting_for_screenshot.state:
        await message.answer("Вы уже выбрали способ оплаты. Отправьте фото/файл или нажмите «Отмена».")
        return
    text = (
        "Выберите способ оплаты подписки:\n\n"
        "— USDT BEP-20\n"
        "— USDT TRC-20\n"
        "— Перевод по номеру карты"
    )
    from bot.keyboards import get_pay_methods_keyboard
    await message.answer(text, reply_markup=get_pay_methods_keyboard())

async def process_pay_open(callback: types.CallbackQuery):
    from bot.keyboards import get_pay_methods_keyboard
    await callback.message.answer("Выберите способ оплаты:", reply_markup=get_pay_methods_keyboard())
    await callback.answer()

async def process_pay_method(callback: types.CallbackQuery, state: FSMContext):
    data = callback.data
    
    # Если уже выбран способ, игнорируем повторные нажатия
    current_state = await state.get_state()
    if current_state == PaymentState.waiting_for_screenshot.state:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer("Способ оплаты уже выбран. Отправьте фото/файл или нажмите «Отмена».")
        return

    settings = _payment_settings()
    method = None
    caption = None

    if data == "pay_bep20":
        method = "bep20"
        caption = (
            f"USDT BEP-20\nАдрес: <code>{settings['bep20_addr']}</code>\n\n"
            "Нажмите на адрес, чтобы скопировать.\n"
            "Отправьте скриншот оплаты фото или файл (например, PDF).\n"
            "Для отмены нажмите кнопку «Отмена» ниже."
        )
    elif data == "pay_trc20":
        method = "trc20"
        caption = (
            f"USDT TRC-20\nАдрес: <code>{settings['trc20_addr']}</code>\n\n"
            "Нажмите на адрес, чтобы скопировать.\n"
            "Отправьте скриншот оплаты фото или файл (например, PDF).\n"
            "Для отмены нажмите кнопку «Отмена» ниже."
        )
    elif data == "pay_card":
        method = "card"
        caption = (
            f"Перевод по карте\nНомер: <code>{settings['card_number']}</code>\n\n"
            "Нажмите на номер, чтобы скопировать.\n"
            "Отправьте скриншот оплаты фото или файл с чеком (например, PDF).\n"
            "Для отмены нажмите кнопку «Отмена» ниже."
        )

    if not method:
        await callback.answer()
        return

    # Убираем клавиатуру выбора способа, чтобы не было повторных нажатий
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await state.set_state(PaymentState.waiting_for_screenshot)
    await state.update_data(payment_method=method)

    # Инструкция и реквизиты + кнопка отмены
    from bot.keyboards import get_cancel_inline_keyboard
    await callback.message.answer(caption, reply_markup=get_cancel_inline_keyboard())
 
    await callback.answer()
 
async def process_pay_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    # Попробуем убрать инлайн-клавиатуру, если осталась
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    # Вернем пользователя на основную клавиатуру
    engine = init_db()
    db_session = get_session(engine)
    try:
        user = db_session.query(User).filter(User.tg_id == callback.from_user.id).first()
        is_admin = _is_admin_user(user)
        await callback.message.answer("Оплата отменена.", reply_markup=get_main_keyboard(is_admin=is_admin))
    finally:
        db_session.close()
    await callback.answer("Действие отменено")

async def process_payment_screenshot(message: types.Message, state: FSMContext, db_session):
    # Ожидаем фото или документ оплаты
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    is_admin = _is_admin_user(user)

    # Проверка отмены
    if _is_cancel_text(message.text or ""):
        await message.answer("Действие отменено.", reply_markup=get_main_keyboard(is_admin=is_admin))
        await state.clear()
        return

    # Получаем file_id из фото или документа
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id

    if not file_id:
        await message.answer("Пожалуйста, отправьте скриншот или файл с чеком.")
        return

    data = await state.get_data()
    method = data.get("payment_method")
    if not method:
        await message.answer("Способ оплаты не выбран. Нажмите /pay и выберите способ.")
        await state.clear()
        return

    try:
        from db.models import PaymentRequest, PaymentMethod, PaymentStatus
        pr = PaymentRequest(
            user_id=user.id,
            method=PaymentMethod(method),
            file_id=file_id,
            status=PaymentStatus.PENDING,
        )
        db_session.add(pr)
        db_session.commit()
        await message.answer(
            "Заявка на оплату отправлена на проверку.",
            reply_markup=get_main_keyboard(is_admin=is_admin)
        )
        # Уведомление админам о новой заявке с кнопкой 'Просмотрено'
        try:
            admins = db_session.query(User).filter(User.role.in_([UserRole.ADMIN, UserRole.SUPERADMIN])).all()
            if admins:
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                info = (
                    f"Новая заявка на оплату #{pr.id}\n"
                    f"Пользователь: {user.username or user.tg_id} (tg_id={user.tg_id})\n"
                    f"Метод: {pr.method.value}\n"
                    f"Создано: {pr.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Смотреть файл/скрин", callback_data=f"pay_view_{pr.id}")],
                    [InlineKeyboardButton(text="Одобрить", callback_data=f"pay_approve_{pr.id}"), InlineKeyboardButton(text="Отклонить", callback_data=f"pay_reject_{pr.id}")],
                    [InlineKeyboardButton(text="Просмотрено", callback_data=f"pay_seen_{pr.id}")],
                ])
                for admin in admins:
                    try:
                        await message.bot.send_message(chat_id=admin.tg_id, text=info, reply_markup=kb)
                    except Exception:
                        pass
        except Exception:
            logger.warning("Не удалось отправить уведомления админам о новой заявке.")
    except Exception:
        await message.answer(
            "Не удалось сохранить заявку. Попробуйте позже или свяжитесь с администратором.",
            reply_markup=get_main_keyboard(is_admin=is_admin)
        )
    finally:
        await state.clear()

def register_user_handlers(dp: Dispatcher):
    """Регистрация обработчиков пользовательских команд"""
    # Базовые команды
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_setlogin, Command("setlogin"))
    dp.message.register(cmd_settimezone, Command("timezone"))
    dp.message.register(cmd_settimezone, Command("settz"))
    
    # Модифицируем обработчики состояний для работы с БД
    async def process_login_input_wrapper(msg: types.Message, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_login_input(msg, state, db_session)
        finally:
            db_session.close()
    
    dp.message.register(process_login_input_wrapper, SetLoginState.waiting_for_login)
    
    # Команды для режимов
    dp.message.register(cmd_addmode, Command("addmode"))
    dp.message.register(process_mode_name, AddModeState.waiting_for_name)
    dp.message.register(process_mode_host, AddModeState.waiting_for_host)
    dp.message.register(process_mode_port, AddModeState.waiting_for_port)
    
    async def process_mode_alias_wrapper(msg: types.Message, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_mode_alias(msg, state, db_session)
        finally:
            db_session.close()
    
    dp.message.register(process_mode_alias_wrapper, AddModeState.waiting_for_alias)
    
    async def cmd_modes_wrapper(msg: types.Message):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await cmd_modes(msg, db_session)
        finally:
            db_session.close()
    
    dp.message.register(cmd_modes_wrapper, Command("modes"))
    
    async def cmd_setmode_wrapper(msg: types.Message, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await cmd_setmode(msg, state, db_session)
        finally:
            db_session.close()
    
    dp.message.register(cmd_setmode_wrapper, Command("setmode"))
    
    async def process_mode_selection_wrapper(msg: types.Message, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_mode_selection(msg, state, db_session)
        finally:
            db_session.close()
    
    dp.message.register(process_mode_selection_wrapper, SetModeState.waiting_for_mode)

    # Callback для выбора режима из инлайн-клавиатуры
    async def process_mode_callback_wrapper(cb: types.CallbackQuery, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_mode_callback(cb, state, db_session)
        finally:
            db_session.close()
    dp.callback_query.register(process_mode_callback_wrapper, F.data.startswith("set_mode_"))
    
    # Команды для расписаний
    dp.message.register(cmd_schedule, Command("schedule"))
    
    async def process_schedule_action_wrapper(msg: types.Message, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_schedule_action(msg, state, db_session)
        finally:
            db_session.close()
    
    dp.message.register(process_schedule_action_wrapper, ScheduleState.waiting_for_action)
    
    async def process_schedule_mode_wrapper(msg: types.Message, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_schedule_mode(msg, state, db_session)
        finally:
            db_session.close()
    
    dp.message.register(process_schedule_mode_wrapper, ScheduleState.waiting_for_mode)

    # Callback для выбора режима при создании расписания
    async def process_schedule_mode_callback_wrapper(cb: types.CallbackQuery, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_schedule_mode_callback(cb, state, db_session)
        finally:
            db_session.close()
    dp.callback_query.register(process_schedule_mode_callback_wrapper, F.data.startswith("schedule_mode_"))
    dp.message.register(process_schedule_start_time, ScheduleState.waiting_for_start_time)
    dp.message.register(process_schedule_end_time, ScheduleState.waiting_for_end_time)
    
    async def process_schedule_confirmation_wrapper(msg: types.Message, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_schedule_confirmation(msg, state, db_session)
        finally:
            db_session.close()
    
    dp.message.register(process_schedule_confirmation_wrapper, ScheduleState.waiting_for_confirmation)

    # Callback для удаления расписания
    dp.callback_query.register(process_schedule_delete_callback, F.data.startswith("delete_schedule_"))

    # Обработчики часового пояса
    async def process_timezone_callback_wrapper(cb: types.CallbackQuery, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_timezone_callback(cb, state, db_session)
        finally:
            db_session.close()
    dp.callback_query.register(process_timezone_callback_wrapper, F.data.startswith("set_timezone_"))

    async def process_timezone_input_wrapper(msg: types.Message, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_timezone_input(msg, state, db_session)
        finally:
            db_session.close()
    dp.message.register(process_timezone_input_wrapper, TimezoneState.waiting_for_timezone_input)
    
    # Статус и помощь
    async def cmd_status_wrapper(msg: types.Message):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await cmd_status(msg, db_session)
        finally:
            db_session.close()
    
    dp.message.register(cmd_status_wrapper, Command("status"))
    dp.message.register(cmd_help, Command("help"))

    # Оплата
    dp.message.register(cmd_pay, Command("pay"))
    # Callback из напоминаний: открыть выбор способа оплаты
    dp.callback_query.register(process_pay_open, F.data == "pay_open")
    # Callback кнопок метода оплаты
    dp.callback_query.register(process_pay_method, F.data == "pay_bep20")
    dp.callback_query.register(process_pay_method, F.data == "pay_trc20")
    dp.callback_query.register(process_pay_method, F.data == "pay_card")
    # Кнопка инлайн-отмены
    dp.callback_query.register(process_pay_cancel, F.data == "pay_cancel")

    async def process_payment_screenshot_wrapper(msg: types.Message, state: FSMContext):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await process_payment_screenshot(msg, state, db_session)
        finally:
            db_session.close()
    # принимаем фото и документы в состоянии ожидания скрина/чека
    dp.message.register(process_payment_screenshot_wrapper, PaymentState.waiting_for_screenshot, F.photo)
    dp.message.register(process_payment_screenshot_wrapper, PaymentState.waiting_for_screenshot, F.document)

    # Отмена
    dp.message.register(lambda msg: cmd_cancel(msg, dp.fsm.get_context(msg.bot, msg.from_user.id, msg.chat.id)), Command("cancel"))
    dp.message.register(lambda msg: cmd_cancel(msg, dp.fsm.get_context(msg.bot, msg.from_user.id, msg.chat.id)), F.text.lower() == "отмена")