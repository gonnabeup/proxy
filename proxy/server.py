import asyncio
import logging
import signal
import sys
import os

# Добавляем корневую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import PROXY_HOST
from db.models import init_db, get_session, User
from proxy.router import StratumRouter

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/proxy_server.log')
    ]
)
logger = logging.getLogger(__name__)

class StratumProxyServer:
    def __init__(self, db_url=None):
        # Если URL не передан, init_db возьмет DATABASE_URL из настроек
        self.db_engine = init_db(db_url)
        self.db_session = get_session(self.db_engine)
        self.router = StratumRouter(self.db_session)
        self.servers = {}  # Словарь для хранения серверов по портам
        self.running = False
    
    async def start(self):
        """Запуск прокси-сервера"""
        self.running = True
        
        # Получаем всех пользователей с активной подпиской
        users = self.db_session.query(User).all()
        
        if not users:
            logger.warning("Нет пользователей в базе данных")
            return
        
        # Создаем серверы для каждого порта пользователя
        for user in users:
            try:
                server = await asyncio.start_server(
                    lambda r, w, port=user.port: self.router.handle_client(r, w, port),
                    PROXY_HOST, user.port
                )
                
                self.servers[user.port] = server
                logger.info(f"Сервер запущен на {PROXY_HOST}:{user.port} для пользователя {user.username}")
                
                # Запускаем сервер
                asyncio.create_task(server.serve_forever())
                
            except Exception as e:
                logger.error(f"Ошибка при запуске сервера на порту {user.port}: {e}")
        
        # Настраиваем обработчики сигналов для корректного завершения
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: asyncio.create_task(self.stop())
            )
        
        logger.info("Stratum-прокси сервер запущен и готов к работе")
    
    async def stop(self):
        """Остановка прокси-сервера"""
        if not self.running:
            return
        
        self.running = False
        logger.info("Останавливаем Stratum-прокси сервер...")
        
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