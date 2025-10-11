import asyncio
import logging
import sys
import os

# Добавляем корневую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.enums import ParseMode

from config.settings import BOT_TOKEN, SCHEDULER_INTERVAL
from db.models import init_db, get_session
from bot.handlers import register_handlers
from proxy.server import StratumProxyServer

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/bot.log')
    ]
)
logger = logging.getLogger(__name__)

async def set_commands(bot: Bot):
    """Установка команд бота"""
    commands = [
        BotCommand(command="/start", description="Начать работу с ботом"),
        BotCommand(command="/setlogin", description="Задать/изменить логин"),
        BotCommand(command="/addmode", description="Добавить режим"),
        BotCommand(command="/modes", description="Список режимов"),
        BotCommand(command="/setmode", description="Выбрать активный режим"),
        BotCommand(command="/schedule", description="Управление расписанием"),
        BotCommand(command="/status", description="Показать статус"),
        BotCommand(command="/help", description="Помощь по командам"),
    ]
    await bot.set_my_commands(commands)

async def scheduler_task(proxy_server):
    """Задача планировщика для проверки расписаний"""
    while True:
        try:
            # Обновление активных режимов на основе расписаний
            # Эта функция будет реализована в proxy_server
            await proxy_server.router.update_active_modes_by_schedule()
            await asyncio.sleep(SCHEDULER_INTERVAL)
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            await asyncio.sleep(SCHEDULER_INTERVAL)

async def main():
    """Основная функция для запуска бота и прокси-сервера"""
    # Инициализация базы данных
    db_engine = init_db()
    db_session = get_session(db_engine)
    
    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Регистрация обработчиков
    register_handlers(dp, db_session)
    
    # Установка команд бота
    await set_commands(bot)
    
    # Запуск прокси-сервера
    proxy_server = StratumProxyServer()
    await proxy_server.start()
    
    # Запуск планировщика
    asyncio.create_task(scheduler_task(proxy_server))
    
    # Запуск бота
    try:
        logger.info("Бот запущен")
        await dp.start_polling(bot)
    finally:
        await proxy_server.stop()
        db_session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        sys.exit(1)