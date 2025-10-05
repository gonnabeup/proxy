import logging
import json
import datetime
from sqlalchemy.orm import Session
import sys
import os

# Добавляем корневую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import User, Mode, Schedule

logger = logging.getLogger(__name__)

def get_user_by_port(session: Session, port: int) -> User:
    """Получение пользователя по порту"""
    return session.query(User).filter(User.port == port).first()

def get_active_mode(session: Session, user_id: int) -> Mode:
    """Получение активного режима пользователя"""
    return session.query(Mode).filter(Mode.user_id == user_id, Mode.is_active == 1).first()

def get_scheduled_mode(session: Session, user_id: int) -> Mode:
    """Получение режима по расписанию"""
    now = datetime.datetime.now()
    current_time = now.strftime("%H:%M")
    
    # Получаем пользователя для определения часового пояса
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    
    # Получаем все расписания пользователя
    schedules = session.query(Schedule).filter(Schedule.user_id == user_id).all()
    
    for schedule in schedules:
        # Проверяем, попадает ли текущее время в диапазон расписания
        if is_time_in_range(current_time, schedule.start_time, schedule.end_time):
            # Возвращаем режим из расписания
            return session.query(Mode).filter(Mode.id == schedule.mode_id).first()
    
    return None

def is_time_in_range(current_time, start_time, end_time):
    """Проверка, находится ли текущее время в диапазоне"""
    # Преобразуем строки времени в объекты datetime.time
    def parse_time(time_str):
        hours, minutes = map(int, time_str.split(':'))
        return datetime.time(hours, minutes)
    
    current = parse_time(current_time)
    start = parse_time(start_time)
    end = parse_time(end_time)
    
    # Проверяем, находится ли текущее время в диапазоне
    if start <= end:
        return start <= current <= end
    else:  # Если диапазон переходит через полночь
        return start <= current or current <= end

def modify_stratum_login(data, new_login):
    """Модифицирует JSON-данные Stratum-протокола, заменяя логин"""
    try:
        # Парсим JSON
        json_data = json.loads(data)
        
        # Проверяем, есть ли поле params
        if 'params' in json_data and isinstance(json_data['params'], list) and len(json_data['params']) > 0:
            # Заменяем первый параметр (логин)
            json_data['params'][0] = new_login
            
        # Преобразуем обратно в строку
        return json.dumps(json_data)
    except Exception as e:
        logger.error(f"Ошибка при модификации логина: {e}")
        return data  # Возвращаем исходные данные в случае ошибки