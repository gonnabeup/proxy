#!/bin/bash

# Cryptoshi Stratum Proxy с Telegram-ботом
# Скрипт установки для Ubuntu

set -e

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Установка Cryptoshi Stratum Proxy с Telegram-ботом ===${NC}"

# Проверка наличия sudo прав
if [ "$(id -u)" != "0" ]; then
   echo -e "${RED}Этот скрипт должен быть запущен с правами sudo${NC}" 1>&2
   exit 1
fi

# Установка зависимостей
echo -e "${YELLOW}Установка системных зависимостей...${NC}"
apt-get update
apt-get install -y python3 python3-pip python3-venv postgresql postgresql-contrib

# Создание пользователя для сервиса (если нужно)
echo -e "${YELLOW}Создание пользователя cryptoshi...${NC}"
if id "cryptoshi" &>/dev/null; then
    echo "Пользователь cryptoshi уже существует"
else
    useradd -m -s /bin/bash cryptoshi
    echo "Пользователь cryptoshi создан"
fi

# Определение текущей директории проекта
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${YELLOW}Установка проекта из директории ${PROJECT_DIR}...${NC}"

# Копирование проекта в домашнюю директорию пользователя cryptoshi
echo -e "${YELLOW}Копирование проекта в домашнюю директорию пользователя...${NC}"
cp -r "$PROJECT_DIR" /home/cryptoshi/bot2.0
chown -R cryptoshi:cryptoshi /home/cryptoshi/bot2.0

# Переход в директорию проекта
cd /home/cryptoshi/bot2.0

# Создание виртуального окружения
echo -e "${YELLOW}Создание виртуального окружения...${NC}"
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей Python
echo -e "${YELLOW}Установка Python зависимостей...${NC}"
pip install --upgrade pip

# Проверка наличия файла requirements.txt
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo -e "${RED}Файл requirements.txt не найден. Устанавливаем основные зависимости...${NC}"
    pip install aiogram SQLAlchemy alembic psycopg2-binary python-dotenv asyncio aiohttp
fi

# Настройка базы данных PostgreSQL
echo -e "${YELLOW}Настройка базы данных...${NC}"
# Создаем пользователя и базу данных PostgreSQL
su - postgres -c "psql -c \"CREATE USER cryptoshi WITH PASSWORD 'cryptoshi';\""
su - postgres -c "psql -c \"CREATE DATABASE cryptoshi OWNER cryptoshi;\""
su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE cryptoshi TO cryptoshi;\""

# Копирование примера конфигурации
echo -e "${YELLOW}Настройка конфигурации...${NC}"
if [ ! -f "config/settings.py" ]; then
    cp config/settings.py.example config/settings.py
    echo "Создан файл конфигурации. Пожалуйста, отредактируйте config/settings.py"
else
    echo "Файл конфигурации уже существует"
fi

# Запуск миграций
echo -e "${YELLOW}Запуск миграций базы данных...${NC}"
alembic upgrade head

# Создание systemd сервиса
echo -e "${YELLOW}Создание systemd сервиса...${NC}"
cat > /etc/systemd/system/cryptoshi.service << EOF
[Unit]
Description=Cryptoshi Stratum Proxy с Telegram-ботом
After=network.target postgresql.service

[Service]
User=cryptoshi
Group=cryptoshi
WorkingDirectory=/home/cryptoshi/bot2.0
ExecStart=/home/cryptoshi/bot2.0/venv/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=cryptoshi

[Install]
WantedBy=multi-user.target
EOF

# Перезагрузка systemd
systemctl daemon-reload

# Настройка прав доступа
echo -e "${YELLOW}Настройка прав доступа...${NC}"
chown -R cryptoshi:cryptoshi /home/cryptoshi/bot2.0

# Запуск сервиса
echo -e "${YELLOW}Запуск сервиса...${NC}"
systemctl enable cryptoshi.service
systemctl start cryptoshi.service

echo -e "${GREEN}=== Установка завершена! ===${NC}"
echo -e "Проверьте статус сервиса: ${YELLOW}systemctl status cryptoshi.service${NC}"
echo -e "Просмотр логов: ${YELLOW}journalctl -u cryptoshi.service${NC}"
echo -e "Не забудьте настроить файл ${YELLOW}config/settings.py${NC} и перезапустить сервис после изменений"