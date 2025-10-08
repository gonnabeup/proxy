import os
from pathlib import Path

# Базовые настройки
BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://simple1:simple1@localhost/proxy_bot')

# Настройки Telegram-бота
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')  # Токен Telegram-бота

# Настройки прокси
DEFAULT_PORT_RANGE = (4000, 4200)  # Диапазон портов для пользователей
PROXY_HOST = '0.0.0.0'  # Хост для прослушивания
SCHEDULER_CHECK_INTERVAL = 60  # Интервал проверки расписаний в секундах

# Настройки логирования
LOG_DIR = BASE_DIR / 'logs'
LOG_LEVEL = 'INFO'

# Создание директории для логов, если она не существует
if not LOG_DIR.exists():
    LOG_DIR.mkdir(parents=True, exist_ok=True)