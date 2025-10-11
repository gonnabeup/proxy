from .user_commands import register_user_handlers
from .admin_commands import register_admin_handlers

def register_handlers(dp, proxy_server=None):
    """Регистрация всех обработчиков бота
    proxy_server: экземпляр StratumProxyServer для операций перезагрузки портов.
    """
    register_user_handlers(dp)
    # Передаём proxy_server в админские обработчики, если доступен
    register_admin_handlers(dp, proxy_server=proxy_server)