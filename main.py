import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from config.settings import (
    BOT_TOKEN, PROXY_HOST, DEFAULT_PORT_RANGE, 
    SCHEDULER_CHECK_INTERVAL, LOG_LEVEL
)
from db.models import init_db, get_session
from proxy.server import StratumProxyServer
from bot.handlers import register_handlers
from scheduler import Scheduler

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
    init_db()
    db_session = get_session()
    
    # Инициализация бота
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    
    # Инициализация прокси-сервера
    proxy_server = StratumProxyServer(
        host=PROXY_HOST,
        port_range=DEFAULT_PORT_RANGE,
        db_session=db_session
    )
    
    # Инициализация планировщика
    scheduler = Scheduler(
        proxy_server=proxy_server,
        check_interval=SCHEDULER_CHECK_INTERVAL
    )
    
    try:
        # Регистрация обработчиков команд
        register_handlers(dp, db_session)
        
        # Запуск прокси-сервера
        await proxy_server.start()
        
        # Запуск планировщика
        await scheduler.start()
        
        # Запуск бота
        logger.info("Бот запущен")
        await dp.start_polling()
    finally:
        # Остановка планировщика
        await scheduler.stop()
        
        # Остановка прокси-сервера
        await proxy_server.stop()
        
        # Закрытие сессии бота
        await bot.session.close()
        
        # Закрытие сессии БД
        db_session.close()
        
        logger.info("Приложение остановлено")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Приложение остановлено пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)