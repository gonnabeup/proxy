from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)

def get_yes_no_keyboard():
    """Клавиатура с кнопками Да/Нет"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Да"))
    builder.add(KeyboardButton(text="Нет"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

def get_main_keyboard(is_admin=False):
    """Основная клавиатура с доступными командами"""
    builder = ReplyKeyboardBuilder()
    
    # Кнопки для всех пользователей
    builder.row(KeyboardButton(text="/status"), KeyboardButton(text="/modes"))
    builder.row(KeyboardButton(text="/setlogin"), KeyboardButton(text="/setmode"))
    builder.row(KeyboardButton(text="/addmode"), KeyboardButton(text="/schedule"))
    builder.row(KeyboardButton(text="/help"))
    
    # Дополнительные кнопки для администраторов
    if is_admin:
        builder.row(KeyboardButton(text="/adduser"), KeyboardButton(text="/listusers"))
        builder.row(KeyboardButton(text="/setsub"), KeyboardButton(text="/setport"))
        builder.row(KeyboardButton(text="/freerange"))
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)

def get_modes_keyboard(modes, action="view"):
    """Инлайн-клавиатура для выбора режима"""
    builder = InlineKeyboardBuilder()
    
    for mode in modes:
        callback_data = f"{action}_mode_{mode.id}"
        button_text = f"{mode.name} ({mode.host}:{mode.port})"
        builder.row(InlineKeyboardButton(text=button_text, callback_data=callback_data))
    
    return builder.as_markup()

def get_schedule_keyboard():
    """Клавиатура для команды расписания"""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="/schedule add"), 
        KeyboardButton(text="/schedule list")
    )
    builder.row(
        KeyboardButton(text="/schedule delete"), 
        KeyboardButton(text="Отмена")
    )
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

def get_schedule_list_keyboard(schedules):
    """Инлайн-клавиатура для списка расписаний"""
    builder = InlineKeyboardBuilder()
    
    for schedule in schedules:
        callback_data = f"delete_schedule_{schedule.id}"
        button_text = f"{schedule.mode.name}: {schedule.start_time}-{schedule.end_time}"
        builder.row(InlineKeyboardButton(text=button_text, callback_data=callback_data))
    
    return builder.as_markup()