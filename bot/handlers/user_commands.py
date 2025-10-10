import logging
import asyncio
from datetime import datetime
from aiogram import Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

from db.models import User, Mode, Schedule, get_session, init_db, UserRole
from bot.keyboards import get_modes_keyboard, get_cancel_keyboard, get_yes_no_keyboard, get_main_keyboard

logger = logging.getLogger(__name__)

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

async def cmd_start(message: types.Message, state: FSMContext = None):
    """Обработчик команды /start"""
    # Получаем сессию БД
    engine = init_db()
    db_session = get_session(engine)
    
    try:
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        is_admin = bool(user and (user.role in (UserRole.ADMIN, UserRole.SUPERADMIN)))
        
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
    await SetLoginState.waiting_for_login.set()
    await message.answer(
        "Введите новый логин для ваших воркеров:",
        reply_markup=get_cancel_keyboard()
    )

async def process_login_input(message: types.Message, state: FSMContext, db_session):
    """Обработка ввода нового логина"""
    new_login = message.text.strip()
    
    if len(new_login) < 3 or len(new_login) > 50:
        await message.answer("Логин должен содержать от 3 до 50 символов. Попробуйте еще раз:")
        return
    
    # Обновляем логин пользователя в БД
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    if user:
        user.login = new_login
        db_session.commit()
        await message.answer(f"Логин успешно изменен на: {new_login}")
    else:
        await message.answer("Вы не зарегистрированы в системе.")
    
    # Сбрасываем состояние FSM
    await state.finish()

async def cmd_addmode(message: types.Message, state: FSMContext):
    """Обработчик команды /addmode"""
    await AddModeState.waiting_for_name.set()
    await message.answer(
        "Введите название режима (например, 'f2pool btc'):",
        reply_markup=get_cancel_keyboard()
    )

async def process_mode_name(message: types.Message, state: FSMContext):
    """Обработка ввода названия режима"""
    mode_name = message.text.strip()
    
    # Сохраняем название в состоянии
    await state.update_data(name=mode_name)
    
    # Переходим к следующему шагу
    await AddModeState.waiting_for_host.set()
    await message.answer("Введите хост пула (например, 'btc.f2pool.com'):")

async def process_mode_host(message: types.Message, state: FSMContext):
    """Обработка ввода хоста пула"""
    mode_host = message.text.strip()
    
    # Сохраняем хост в состоянии
    await state.update_data(host=mode_host)
    
    # Переходим к следующему шагу
    await AddModeState.waiting_for_port.set()
    await message.answer("Введите порт пула (например, '3333'):")

async def process_mode_port(message: types.Message, state: FSMContext):
    """Обработка ввода порта пула"""
    try:
        mode_port = int(message.text.strip())
        
        # Сохраняем порт в состоянии
        await state.update_data(port=mode_port)
        
        # Переходим к следующему шагу
        await AddModeState.waiting_for_alias.set()
        await message.answer("Введите алиас для пула (например, 'smagin83'):")
    except ValueError:
        await message.answer("Порт должен быть числом. Попробуйте еще раз:")

async def process_mode_alias(message: types.Message, state: FSMContext, db_session):
    """Обработка ввода алиаса для пула"""
    mode_alias = message.text.strip()
    
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
        
        await message.answer(
            f"Режим успешно добавлен!\n\n"
            f"Название: {name}\n"
            f"Хост: {host}\n"
            f"Порт: {port}\n"
            f"Алиас: {mode_alias}"
        )
    else:
        await message.answer("Вы не зарегистрированы в системе.")
    
    # Сбрасываем состояние FSM
    await state.finish()

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
    
    await SetModeState.waiting_for_mode.set()
    await message.answer(
        "Выберите режим для активации:",
        reply_markup=get_modes_keyboard(modes)
    )

async def process_mode_selection(message: types.Message, state: FSMContext, db_session):
    """Обработка выбора режима"""
    try:
        mode_id = int(message.text.strip())
        
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        mode = db_session.query(Mode).filter(Mode.id == mode_id, Mode.user_id == user.id).first()
        
        if not mode:
            await message.answer("Режим не найден. Попробуйте еще раз.")
            return
        
        # Устанавливаем выбранный режим как активный
        user.active_mode_id = mode.id
        db_session.commit()
        
        await message.answer(f"Активный режим установлен: {mode.name}")
    except ValueError:
        await message.answer("Пожалуйста, введите номер режима.")
    finally:
        # Сбрасываем состояние FSM
        await state.finish()

async def cmd_schedule(message: types.Message, state: FSMContext):
    """Обработчик команды /schedule"""
    await ScheduleState.waiting_for_action.set()
    await message.answer(
        "Выберите действие:\n"
        "1. Добавить расписание (add)\n"
        "2. Показать расписания (list)\n"
        "3. Удалить расписание (delete)",
        reply_markup=get_cancel_keyboard()
    )

async def process_schedule_action(message: types.Message, state: FSMContext, db_session):
    """Обработка выбора действия с расписанием"""
    action = message.text.strip().lower()
    
    if action in ['add', '1', 'добавить']:
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        modes = db_session.query(Mode).filter(Mode.user_id == user.id).all()
        
        if not modes:
            await message.answer("У вас пока нет добавленных режимов. Используйте /addmode для добавления.")
            await state.finish()
            return
        
        await ScheduleState.waiting_for_mode.set()
        await message.answer(
            "Выберите режим для расписания:",
            reply_markup=get_modes_keyboard(modes)
        )
    
    elif action in ['list', '2', 'список']:
        await show_schedules(message, db_session)
        await state.finish()
    
    elif action in ['delete', '3', 'удалить']:
        # Логика удаления расписания
        await message.answer("Функция удаления расписания будет доступна в следующей версии.")
        await state.finish()
    
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
        await ScheduleState.waiting_for_start_time.set()
        await message.answer(
            "Введите время начала в формате ЧЧ:ММ (например, 08:30):",
            reply_markup=get_cancel_keyboard()
        )
    except ValueError:
        await message.answer("Пожалуйста, введите номер режима.")

async def process_schedule_start_time(message: types.Message, state: FSMContext):
    """Обработка ввода времени начала расписания"""
    start_time = message.text.strip()
    
    # Проверяем формат времени
    try:
        datetime.strptime(start_time, "%H:%M")
        
        # Сохраняем время начала в состоянии
        await state.update_data(start_time=start_time)
        
        # Переходим к следующему шагу
        await ScheduleState.waiting_for_end_time.set()
        await message.answer("Введите время окончания в формате ЧЧ:ММ (например, 16:30):")
    except ValueError:
        await message.answer("Неверный формат времени. Используйте формат ЧЧ:ММ (например, 08:30).")

async def process_schedule_end_time(message: types.Message, state: FSMContext):
    """Обработка ввода времени окончания расписания"""
    end_time = message.text.strip()
    
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
        await ScheduleState.waiting_for_confirmation.set()
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
            
            await message.answer("Расписание успешно создано!")
        else:
            await message.answer("Вы не зарегистрированы в системе.")
    else:
        await message.answer("Создание расписания отменено.")
    
    # Сбрасываем состояние FSM
    await state.finish()

async def show_schedules(message: types.Message, db_session):
    """Показать список расписаний пользователя"""
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    
    if not user:
        await message.answer("Вы не зарегистрированы в системе.")
        return
    
    schedules = db_session.query(Schedule).filter(Schedule.user_id == user.id).all()
    
    if not schedules:
        await message.answer("У вас пока нет добавленных расписаний.")
        return
    
    response = "Ваши расписания:\n\n"
    for i, schedule in enumerate(schedules, 1):
        mode = db_session.query(Mode).filter(Mode.id == schedule.mode_id).first()
        mode_name = mode.name if mode else "Неизвестный режим"
        
        response += f"{i}. {mode_name}\n"
        response += f"   Время: {schedule.start_time} - {schedule.end_time}\n\n"
    
    await message.answer(response)

async def cmd_status(message: types.Message, db_session):
    """Обработчик команды /status"""
    user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
    
    if not user:
        await message.answer("Вы не зарегистрированы в системе.")
        return
    
    active_mode = None
    if user.active_mode_id:
        active_mode = db_session.query(Mode).filter(Mode.id == user.active_mode_id).first()
    
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

async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    help_text = (
        "Доступные команды:\n\n"
        "/start - Начать работу с ботом\n"
        "/setlogin - Задать/изменить логин для воркеров\n"
        "/addmode - Добавить новый режим пула\n"
        "/modes - Показать список ваших режимов\n"
        "/setmode - Выбрать активный режим\n"
        "/schedule - Управление расписанием\n"
        "/status - Показать текущий статус\n"
        "/help - Показать эту справку\n\n"
        "Для подключения майнеров используйте:\n"
        "Хост: <IP-адрес сервера>\n"
        "Порт: <Ваш уникальный порт>\n"
        "Логин: <Ваш логин>\n"
        "Пароль: x"
    )
    await message.answer(help_text)

async def cmd_cancel(message: types.Message, state: FSMContext):
    """Обработчик команды отмены"""
    current_state = await state.get_state()
    if current_state is not None:
        await state.finish()
        await message.answer("Действие отменено.")
    else:
        await message.answer("Нет активного действия для отмены.")

def register_user_handlers(dp: Dispatcher):
    """Регистрация обработчиков пользовательских команд"""
    # Базовые команды
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_setlogin, Command("setlogin"))
    
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
    
    # Отмена
    dp.message.register(lambda msg: cmd_cancel(msg, dp.fsm.get_context(msg.bot, msg.from_user.id, msg.chat.id)), Command("cancel"))
    dp.message.register(lambda msg: cmd_cancel(msg, dp.fsm.get_context(msg.bot, msg.from_user.id, msg.chat.id)), F.text.lower() == "отмена")