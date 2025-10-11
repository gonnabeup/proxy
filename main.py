import asyncio
import os
import sys

# Ensure project root is on sys.path so 'bot' package is importable
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode

from config.settings import (
    BOT_TOKEN, PROXY_HOST, DEFAULT_PORT_RANGE, 
    SCHEDULER_CHECK_INTERVAL, LOG_LEVEL
)
from db.models import init_db, get_session
from proxy.server import StratumProxyServer
from bot.handlers import register_handlers
from bot.scheduler import Scheduler

# Настройка логирования
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/app.log')
    ]
)
logger = logging.getLogger(__name__)

async def main():
    """Основная функция запуска приложения"""
    logger.info("Запуск приложения...")
    
    # Инициализация базы данных
    engine = init_db()
    
    # Инициализация бота
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Инициализация прокси-сервера
    proxy_server = StratumProxyServer()
    
    # Инициализация планировщика
    scheduler = Scheduler(
        proxy_server=proxy_server,
        check_interval=SCHEDULER_CHECK_INTERVAL
    )
    
    try:
        # Регистрация обработчиков команд
        register_handlers(dp)
        
        # Запуск прокси-сервера
        await proxy_server.start()
        
        # Запуск планировщика
        await scheduler.start()
        
        # Запуск бота
        logger.info("Бот запущен")
        await dp.start_polling(bot)
    finally:
        # Остановка планировщика
        await scheduler.stop()
        
        # Остановка прокси-сервера
        await proxy_server.stop()
        
        logger.info("Приложение остановлено")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Приложение остановлено пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)