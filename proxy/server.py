import asyncio
import logging
import signal
import sys
import os

# Добавляем корневую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import PROXY_HOST, LOG_DIR, LOG_LEVEL, SCHEDULER_CHECK_INTERVAL
from db.models import init_db, get_session, User
from proxy.router import StratumRouter

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_DIR / 'proxy_server.log'))
    ]
)
logger = logging.getLogger(__name__)
# Повышаем детализацию для роутера
logging.getLogger('proxy.router').setLevel(logging.DEBUG)

class StratumProxyServer:
    def __init__(self, db_url=None):
        # Если URL не передан, init_db возьмет DATABASE_URL из настроек
        self.db_engine = init_db(db_url)
        self.db_session = get_session(self.db_engine)
        self.router = StratumRouter(self.db_session)
        self.servers = {}  # Словарь для хранения серверов по портам
        self.running = False
        self.schedule_task = None

    async def _start_server_for_user(self, user: User):
        """Запуск сервера для конкретного пользователя"""
        port = user.port
        host = PROXY_HOST
        try:
            server = await asyncio.start_server(
                lambda r, w: self.router.handle_client(r, w, port),
                host,
                port
            )
            self.servers[port] = server
            logger.info(f"Сервер запущен для пользователя {user.username} на порту {port}")
        except Exception as e:
            logger.error(f"Не удалось запустить сервер для пользователя {user.username} на порту {port}: {e}")

    async def start(self):
        """Запуск прокси-сервера"""
        self.running = True
        
        # Получаем всех пользователей с активной подпиской и валидным портом
        users = [u for u in self.db_session.query(User).all() if u.port and u.is_subscription_active()]
        
        if not users:
            logger.warning("Нет активных пользователей в базе данных")
            return
        
        # Создаем серверы для каждого порта пользователя
        for user in users:
            await self._start_server_for_user(user)
        
        # Настраиваем обработчики сигналов для корректного завершения (безопасно для Windows)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
            except (NotImplementedError, RuntimeError):
                logger.debug("Обработчики сигналов недоступны на этой платформе; используем KeyboardInterrupt")
        
        # Запускаем фоновые проверки расписаний режимов
        self.schedule_task = asyncio.create_task(self._schedule_loop())
        
        logger.info("Stratum-прокси сервер запущен и готов к работе")

    async def stop(self):
        """Остановка прокси-сервера"""
        if not self.running:
            return
        
        self.running = False
        logger.info("Останавливаем Stratum-прокси сервер...")
        
        # Останавливаем фоновые задачи
        if self.schedule_task:
            self.schedule_task.cancel()
            try:
                await self.schedule_task
            except asyncio.CancelledError:
                pass
            self.schedule_task = None
        
        # Закрываем все соединения
        self.router.close_all_connections()
        
        # Останавливаем все серверы
        for port, server in self.servers.items():
            server.close()
            await server.wait_closed()
            logger.info(f"Сервер на порту {port} остановлен")
        
        self.servers.clear()
        
        # Закрываем сессию базы данных
        self.db_session.close()
        
        logger.info("Stratum-прокси сервер остановлен")

    async def reload_ports(self):
        """Перезагрузка портов (например, после добавления новых пользователей)"""
        # Останавливаем текущие серверы
        for port, server in self.servers.items():
            server.close()
            await server.wait_closed()
            logger.info(f"Сервер на порту {port} остановлен для перезагрузки")
        
        self.servers.clear()
        
        # Обновляем сессию базы данных
        self.db_session.close()
        self.db_session = get_session(self.db_engine)
        self.router = StratumRouter(self.db_session)
        
        # Запускаем серверы заново
        await self.start()
        
        logger.info("Порты перезагружены")

    async def _schedule_loop(self):
        """Фоновая проверка расписаний и активация режимов"""
        while self.running:
            try:
                await self.router.update_active_modes_by_schedule()
            except Exception as e:
                logger.error(f"Ошибка обновления режимов по расписанию: {e}")
            await asyncio.sleep(SCHEDULER_CHECK_INTERVAL)

async def main():
    """Основная функция для запуска сервера"""
    server = StratumProxyServer()
    await server.start()
    
    # Держим сервер запущенным
    while server.running:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Сервер остановлен пользователем")
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        sys.exit(1)