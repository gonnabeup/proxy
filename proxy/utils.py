import logging
import json
import datetime
from zoneinfo import ZoneInfo
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
    # Определяем часовой пояс пользователя
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    tz_name = user.timezone or "Europe/Moscow"
    now = datetime.datetime.now(ZoneInfo(tz_name))
    current_time = now.strftime("%H:%M")
    
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
    # Универсальный парсер: принимает строки "HH:MM" или datetime.time
    def parse_time(t):
        if isinstance(t, datetime.time):
            return t
        if isinstance(t, str):
            hours, minutes = map(int, t.split(':'))
            return datetime.time(hours, minutes)
        # Попытка привести к строке
        ts = str(t)
        hours, minutes = map(int, ts.split(':'))
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
        # Удаляем возможный BOM и приводим к строке
        if isinstance(data, bytes):
            text = data.decode('utf-8-sig', errors='ignore')
        else:
            text = data or ""
            if text.startswith('\ufeff'):
                text = text.lstrip('\ufeff')

        # Некоторые клиенты отправляют несколько JSON-объектов одним буфером.
        # Разберём последовательность объектов с помощью raw_decode и модифицируем только authorize/submit.
        decoder = json.JSONDecoder()
        idx = 0
        length = len(text)
        objects = []
        while idx < length:
            # Пропускаем пробелы и переводы строк
            while idx < length and text[idx].isspace():
                idx += 1
            if idx >= length:
                break
            obj, next_idx = decoder.raw_decode(text, idx)
            if isinstance(obj, dict) and obj.get('method') in ("mining.authorize", "mining.submit"):
                params = obj.get('params')
                if isinstance(params, list) and params:
                    obj['params'][0] = new_login
            objects.append(obj)
            idx = next_idx

        # Если что-то распарсили, вернём обратно как NDJSON (по одному объекту на строку)
        if objects:
            return "\n".join(json.dumps(o) for o in objects)
        # Если не получилось распарсить как последовательность, попробуем обычный случай
        json_data = json.loads(text)
        if isinstance(json_data, dict) and json_data.get('method') in ("mining.authorize", "mining.submit"):
            params = json_data.get('params')
            if isinstance(params, list) and params:
                json_data['params'][0] = new_login
        return json.dumps(json_data)
    except Exception as e:
        logger.error(f"Ошибка при модификации логина: {e}")
        # Возвращаем исходные данные в случае ошибки, предварительно удалив BOM если он есть
        try:
            if isinstance(data, bytes):
                return data.decode('utf-8', errors='ignore')
            return data.lstrip('\ufeff') if isinstance(data, str) else data
        except Exception:
            return data