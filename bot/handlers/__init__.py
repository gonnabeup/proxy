from .user_commands import register_user_handlers
from .admin_commands import register_admin_handlers

def register_handlers(dp):
    """Регистрация всех обработчиков бота"""
    register_user_handlers(dp)
    register_admin_handlers(dp)