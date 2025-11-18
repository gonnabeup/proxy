import asyncio
import os
import sys
import logging
import io
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from config.settings import BOT_TOKEN, SCHEDULER_CHECK_INTERVAL, LOG_LEVEL
from db.models import init_db
from bot.handlers import register_handlers
from bot.scheduler import Scheduler
from main import set_commands

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')),
        logging.FileHandler('logs/app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

async def main():
    engine = init_db()
    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    scheduler = Scheduler(
        proxy_server=None,
        check_interval=SCHEDULER_CHECK_INTERVAL,
        bot=bot,
    )

    try:
        register_handlers(dp, proxy_server=None)
        await set_commands(bot)
        await scheduler.start()
        await dp.start_polling(bot)
    finally:
        await scheduler.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)