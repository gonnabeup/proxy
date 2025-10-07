import logging
from aiogram import Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from db.models import User, Mode, Schedule

logger = logging.getLogger(__name__)

async def cmd_admin_help(message: types.Message):
    """Обработчик команды /admin_help"""
    help_text = (
        "Административные команды:\n\n"
        "/admin_help - Показать эту справку\n"
        "/users - Показать список пользователей\n"
        "/stats - Показать статистику системы"
    )
    await message.answer(help_text)

async def cmd_users(message: types.Message, db_session):
    """Обработчик команды /users"""
    # Проверка прав администратора (пример)
    if message.from_user.id != 123456789:  # Замените на ID администратора
        await message.answer("У вас нет прав для выполнения этой команды.")
        return
    
    users = db_session.query(User).all()
    
    if not users:
        await message.answer("Пользователи не найдены.")
        return
    
    response = "Список пользователей:\n\n"
    for i, user in enumerate(users, 1):
        response += f"{i}. ID: {user.id}, TG: {user.tg_id}, Логин: {user.login}\n"
        response += f"   Порт: {user.port}, Подписка до: {user.subscription_until.strftime('%d.%m.%Y')}\n\n"
    
    await message.answer(response)

async def cmd_stats(message: types.Message, db_session):
    """Обработчик команды /stats"""
    # Проверка прав администратора (пример)
    if message.from_user.id != 123456789:  # Замените на ID администратора
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

def register_admin_handlers(dp: Dispatcher, db_session):
    """Регистрация обработчиков административных команд"""
    dp.message.register(cmd_admin_help, Command("admin_help"))
    dp.message.register(lambda msg: cmd_users(msg, db_session), Command("users"))
    dp.message.register(lambda msg: cmd_stats(msg, db_session), Command("stats"))