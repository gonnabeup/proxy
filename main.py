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
from aiogram.types import BotCommand, BotCommandScopeDefault, BotCommandScopeChat

from config.settings import (
    BOT_TOKEN, PROXY_HOST, DEFAULT_PORT_RANGE, 
    SCHEDULER_CHECK_INTERVAL, LOG_LEVEL
)
from db.models import init_db, get_session, User, UserRole
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

async def set_commands(bot: Bot):
    # Команды по умолчанию для всех пользователей
    default_commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="setlogin", description="Установить логин"),
        BotCommand(command="addmode", description="Добавить режим"),
        BotCommand(command="modes", description="Список режимов"),
        BotCommand(command="setmode", description="Выбрать режим"),
        BotCommand(command="schedule", description="Расписание прокси"),
        BotCommand(command="status", description="Проверка статуса"),
        BotCommand(command="timezone", description="Установить часовой пояс"),
        BotCommand(command="pay", description="Оплатить подписку"),
        BotCommand(command="help", description="Справка по командам"),
    ]

    admin_commands_only = [
        BotCommand(command="admin_help", description="Справка для админа"),
        BotCommand(command="users", description="Пользователи"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="adduser", description="Добавить пользователя"),
        BotCommand(command="setsub", description="Изменить подписку"),
        BotCommand(command="setport", description="Задать порт"),
        BotCommand(command="freerange", description="Свободные порты"),
        BotCommand(command="listusers", description="Список логинов"),
        BotCommand(command="reloadport", description="Перезагрузить порт"),
        BotCommand(command="payments", description="Запросы на оплату"),
        BotCommand(command="extendsub", description="Продлить подписку"),
    ]

    # Устанавливаем админские команды для чатов администраторов
    engine = init_db()
    db_session = get_session(engine)
    try:
        admins = db_session.query(User).filter(User.role.in_([UserRole.ADMIN, UserRole.SUPERADMIN])).all()
        # Импортируем модели для выборки админов
        from db.models import User, UserRole
        
        # Устанавливаем команды только для приватных чатов
        from aiogram.types import BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
        await bot.set_my_commands(default_commands, scope=BotCommandScopeAllPrivateChats())
        # Очищаем меню команд в группах/супергруппах
        await bot.set_my_commands([], scope=BotCommandScopeAllGroupChats())
        
        # Список админов/суперадминов
        admins = await User.get_admins_roles(bot) if hasattr(User, 'get_admins_roles') else None
        if admins is None:
            # Фоллбек: выборка по ролям из БД
            from sqlalchemy import select
            from db.models import async_session
            async with async_session() as session:
                result = await session.execute(select(User).where(User.role.in_([UserRole.ADMIN, UserRole.SUPERADMIN])))
                admins = result.scalars().all()
        
        # Для каждого админа ставим расширенное меню в его приватном чате
        for admin in admins:
            tg_id = getattr(admin, "tg_id", None)
            if not tg_id:
                continue
            # Объединяем дефолтные + админские
            admin_commands = default_commands + admin_commands_only
            try:
                await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=tg_id))
            except Exception:
                # Игнорируем ошибки установки для конкретного чата
                pass

    finally:
        db_session.close()

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
        check_interval=SCHEDULER_CHECK_INTERVAL,
        bot=bot
    )
    
    try:
        # Регистрация обработчиков команд (передаем proxy_server для точечных перезагрузок)
        register_handlers(dp, proxy_server=proxy_server)

        # Установка команд бота
        await set_commands(bot)
        
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