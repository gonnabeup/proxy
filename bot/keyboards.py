from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    keyboard.add(KeyboardButton("Отмена"))
    return keyboard

def get_yes_no_keyboard():
    """Клавиатура с кнопками Да/Нет"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(KeyboardButton("Да"), KeyboardButton("Нет"))
    return keyboard

def get_main_keyboard(is_admin=False):
    """Основная клавиатура с доступными командами"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    
    # Кнопки для всех пользователей
    keyboard.add(KeyboardButton("/status"), KeyboardButton("/modes"))
    keyboard.add(KeyboardButton("/setlogin"), KeyboardButton("/setmode"))
    keyboard.add(KeyboardButton("/addmode"), KeyboardButton("/schedule"))
    keyboard.add(KeyboardButton("/help"))
    
    # Дополнительные кнопки для администраторов
    if is_admin:
        keyboard.add(KeyboardButton("/adduser"), KeyboardButton("/listusers"))
        keyboard.add(KeyboardButton("/setsub"), KeyboardButton("/setport"))
        keyboard.add(KeyboardButton("/freerange"))
    
    return keyboard

def get_modes_keyboard(modes, action="view"):
    """Инлайн-клавиатура для выбора режима"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for mode in modes:
        callback_data = f"{action}_mode_{mode.id}"
        button_text = f"{mode.name} ({mode.host}:{mode.port})"
        keyboard.add(InlineKeyboardButton(text=button_text, callback_data=callback_data))
    
    return keyboard

def get_schedule_keyboard():
    """Клавиатура для команды расписания"""
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    keyboard.add(KeyboardButton("/schedule add"), KeyboardButton("/schedule list"))
    keyboard.add(KeyboardButton("/schedule delete"), KeyboardButton("Отмена"))
    return keyboard

def get_schedule_list_keyboard(schedules):
    """Инлайн-клавиатура для списка расписаний"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    for schedule in schedules:
        callback_data = f"delete_schedule_{schedule.id}"
        button_text = f"{schedule.mode.name}: {schedule.start_time}-{schedule.end_time}"
        keyboard.add(InlineKeyboardButton(text=button_text, callback_data=callback_data))
    
    return keyboard