from .user_commands import register_user_handlers
from .admin_commands import register_admin_handlers

def register_handlers(dp, db_session):
    """Регистрация всех обработчиков бота"""
    register_user_handlers(dp, db_session)
    register_admin_handlers(dp, db_session)