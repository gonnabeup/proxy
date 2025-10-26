from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

def get_cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Отмена"))
    # Один раз показать, затем скрыть после нажатия
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

def get_yes_no_keyboard():
    """Клавиатура с кнопками Да/Нет"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Да"))
    builder.add(KeyboardButton(text="Нет"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

def get_main_keyboard(is_admin=False):
    """Основная клавиатура с доступными командами (обновлённая структура)"""
    builder = ReplyKeyboardBuilder()
    
    # Основные разделы
    builder.row(KeyboardButton(text="Статус"))
    builder.row(KeyboardButton(text="Управление пулами"), KeyboardButton(text="Настройки"))
    builder.row(KeyboardButton(text="Оплата подписки"), KeyboardButton(text="Помощь"))
    
    # Дополнительные кнопки для администраторов (оставляем как есть)
    if is_admin:
        builder.row(KeyboardButton(text="/adduser"), KeyboardButton(text="/listusers"))
        builder.row(KeyboardButton(text="/setsub"), KeyboardButton(text="/setport"))
        builder.row(KeyboardButton(text="/freerange"), KeyboardButton(text="/payments"))
        builder.row(KeyboardButton(text="/extendsub"))
    
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)

# ===== Новые разделы меню =====

def get_pools_management_keyboard():
    """Клавиатура раздела "Управление пулами"""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Добавить пул"), KeyboardButton(text="Удалить пул"))
    builder.row(KeyboardButton(text="Список пулов"))
    builder.row(KeyboardButton(text="Назад"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def get_settings_keyboard():
    """Клавиатура раздела "Настройки"""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Сменить логин"), KeyboardButton(text="Установить часовой пояс"))
    builder.row(KeyboardButton(text="Назад"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=False)


def get_modes_keyboard(modes, action="view"):
    """Инлайн-клавиатура для выбора режима"""
    builder = InlineKeyboardBuilder()
    
    for mode in modes:
        callback_data = f"{action}_mode_{mode.id}"
        button_text = f"{mode.name} ({mode.host}:{mode.port})"
        builder.row(InlineKeyboardButton(text=button_text, callback_data=callback_data))
    
    return builder.as_markup()


def get_delete_modes_keyboard(modes, page: int = 1, page_size: int = 5):
    """Инлайн-клавиатура для удаления пулов с пагинацией по 5 на страницу"""
    builder = InlineKeyboardBuilder()

    total = len(modes)
    if total == 0:
        return builder.as_markup()

    # Расчет среза
    start = (page - 1) * page_size
    end = start + page_size
    slice_modes = modes[start:end]

    for mode in slice_modes:
        # Показываем название и хост:порт, можно добавить алиас при необходимости
        text = f"{mode.name} ({mode.host}:{mode.port})"
        builder.row(InlineKeyboardButton(text=text, callback_data=f"del_mode_{mode.id}"))

    # Навигация
    pages = (total + page_size - 1) // page_size
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"del_prev_{page - 1}"))
    if page < pages:
        nav_row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"del_next_{page + 1}"))
    if nav_row:
        builder.row(*nav_row)

    return builder.as_markup()


def get_timezone_keyboard():
    """Инлайн-клавиатура выбора часового пояса"""
    builder = InlineKeyboardBuilder()
    # Популярные варианты
    builder.row(InlineKeyboardButton(text="Москва/Питер", callback_data="set_timezone_Europe/Moscow"))
    builder.row(InlineKeyboardButton(text="Новосибирск", callback_data="set_timezone_Asia/Novosibirsk"))
    builder.row(InlineKeyboardButton(text="Иркутск", callback_data="set_timezone_Asia/Irkutsk"))
    builder.row(InlineKeyboardButton(text="UTC", callback_data="set_timezone_UTC"))
    builder.row(InlineKeyboardButton(text="Другое", callback_data="set_timezone_OTHER"))
    return builder.as_markup()


def get_schedule_keyboard():
    """Клавиатура для команды расписания (устарела, не используется)"""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_schedule_action_keyboard():
    """Клавиатура выбора действия расписания: 1, 2, 3"""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="1"),
        KeyboardButton(text="2"),
        KeyboardButton(text="3")
    )
    builder.row(KeyboardButton(text="Отмена"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def get_schedule_list_keyboard(schedules):
    """Инлайн-клавиатура для списка расписаний"""
    builder = InlineKeyboardBuilder()
    
    for schedule in schedules:
        callback_data = f"delete_schedule_{schedule.id}"
        button_text = f"{schedule.mode.name}: {schedule.start_time}-{schedule.end_time}"
        builder.row(InlineKeyboardButton(text=button_text, callback_data=callback_data))
    
    return builder.as_markup()


def get_pool_link_keyboard(url: str = "https://btc.f2pool.com"):
    """Инлайн-клавиатура с тремя кнопками, ведущими на указанный URL"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="1", url=url),
        InlineKeyboardButton(text="2", url=url),
        InlineKeyboardButton(text="3", url=url),
    )
    return builder.as_markup()


def get_pay_methods_keyboard():
    """Инлайн-клавиатура выбора способа оплаты"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="USDT BEP-20", callback_data="pay_bep20"))
    builder.row(InlineKeyboardButton(text="USDT TRC-20", callback_data="pay_trc20"))
    builder.row(InlineKeyboardButton(text="Перевод по карте", callback_data="pay_card"))
    return builder.as_markup()


def get_cancel_inline_keyboard():
    """Инлайн-клавиатура с кнопкой отмены для процессов (например, оплаты)"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Отмена", callback_data="pay_cancel"))
    return builder.as_markup()

# Новая клавиатура с кнопкой «Назад»
def get_back_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Назад"))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)