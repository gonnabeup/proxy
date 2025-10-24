import os
from pathlib import Path

# Базовые настройки
BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://simple1:simple1@localhost/proxy_bot')

# Настройки Telegram-бота
# Токен Telegram-бота
# Поддерживаем две переменные окружения для совместимости:
# - BOT_TOKEN (приоритетно)
# - TELEGRAM_TOKEN (фолбэк)
BOT_TOKEN = os.getenv('BOT_TOKEN', os.getenv('TELEGRAM_TOKEN', ''))
TELEGRAM_TOKEN = BOT_TOKEN  # сохранение совместимости со старым именем

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

# Настройки оплаты
WALLET_BEP20_ADDRESS = os.getenv('WALLET_BEP20_ADDRESS', '')
WALLET_TRC20_ADDRESS = os.getenv('WALLET_TRC20_ADDRESS', '')
CARD_NUMBER = os.getenv('CARD_NUMBER', '')
# Фолбек для курса USD→RUB, если API недоступен
USD_RUB_FALLBACK = float(os.getenv('USD_RUB_FALLBACK', '100'))

# Настройки пула соединений БД
DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '200'))
DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', '400'))
DB_POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', '60'))
DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', '1800'))
DB_POOL_PRE_PING = os.getenv('DB_POOL_PRE_PING', '1').lower() in ('1', 'true', 'yes')