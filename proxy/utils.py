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

# --- вспомогательные функции работы с БД и режимами ---

def get_user_by_port(db_session: Session, port: int) -> User | None:
    try:
        return db_session.query(User).filter(User.port == port).first()
    except Exception as e:
        logger.error(f"Ошибка при получении пользователя по порту {port}: {e}")
        return None


def get_active_mode(db_session: Session, user_id: int) -> Mode | None:
    try:
        return db_session.query(Mode).filter(Mode.user_id == user_id, Mode.is_active == 1).first()
    except Exception as e:
        logger.error(f"Ошибка при получении активного режима пользователя {user_id}: {e}")
        return None


def get_scheduled_mode(db_session: Session, user_id: int) -> Mode | None:
    """Возвращает режим, активный по расписанию в локальном времени пользователя.
    Поддерживает только интервалы времени (без поля weekday).
    """
    try:
        user = db_session.query(User).filter(User.id == user_id).first()
        if not user:
            return None
        tz = ZoneInfo(user.timezone or 'UTC')
        now_local = datetime.datetime.now(tz)
        time_str = now_local.strftime('%H:%M')

        schedules = db_session.query(Schedule).filter(Schedule.user_id == user_id).all()
        for sched in schedules:
            # sched.start_time / sched.end_time хранятся как строки "HH:MM" (или time)
            if is_time_in_range(time_str, sched.start_time, sched.end_time):
                mode = db_session.query(Mode).filter(Mode.id == sched.mode_id).first()
                return mode
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении расписания для пользователя {user_id}: {e}")
        return None


# --- модификация кредов Stratum ---

def is_time_in_range(current_time, start_time, end_time):
    """Проверка, находится ли текущее время в диапазоне [start_time, end_time].
    Принимает строки формата "HH:MM" или объекты datetime.time. Корректно обрабатывает диапазоны через полночь.
    """
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


def modify_stratum_credentials(data, user_login, alias):
    """Модифицирует JSON-данные Stratum:
    - mining.authorize: устанавливает alias (если alias есть), иначе login
    - mining.submit: устанавливает worker = alias
    Поддерживает NDJSON (несколько JSON-объектов в одном буфере) и BOM.
    Добавлено подробное логирование изменений параметров.
    """
    try:
        # Приведение к строке и удаление BOM
        if isinstance(data, bytes):
            text = data.decode('utf-8-sig', errors='ignore')
        else:
            text = data or ""
            if text.startswith('\ufeff'):
                text = text.lstrip('\ufeff')

        decoder = json.JSONDecoder()
        idx = 0
        length = len(text)
        objects = []
        changed_any = False

        while idx < length:
            # Пропускаем пробелы и переводы строк
            while idx < length and text[idx].isspace():
                idx += 1
            if idx >= length:
                break
            try:
                obj, next_idx = decoder.raw_decode(text, idx)
            except Exception:
                # Если не удалось разобрать последовательность — выйдем и попробуем обычный разбор ниже
                objects = []
                break
            if isinstance(obj, dict):
                method = obj.get('method')
                params = obj.get('params')
                if isinstance(params, list) and params:
                    if method == "mining.authorize":
                        old_user = params[0]
                        if alias:
                            try:
                                suffix = old_user.split('.', 1)[1] if isinstance(old_user, str) and '.' in old_user else None
                            except Exception:
                                suffix = None
                            new_user = f"{alias}.{suffix}" if suffix else alias
                        else:
                            new_user = user_login
                        obj['params'][0] = new_user
                        changed_any = True
                        logger.info(f"authorize: old='{old_user}' -> new='{new_user}' (alias + preserved worker)")
                    elif method == "mining.submit":
                        # Не переписываем worker; оставляем как есть, только логируем
                        if isinstance(params, list) and params:
                            worker_val = params[0]
                            logger.info(f"submit: worker stays='{worker_val}' (no rewrite)")
            objects.append(obj)
            idx = next_idx

        if objects:
            # Если был NDJSON, вернём строки по объекту
            if changed_any:
                return "\n".join(json.dumps(o) for o in objects)
            else:
                return text

        # Обычный разбор одного JSON-объекта
        json_data = json.loads(text)
        if isinstance(json_data, dict):
            method = json_data.get('method')
            params = json_data.get('params')
            if isinstance(params, list) and params:
                if method == "mining.authorize":
                    old_user = params[0]
                    if alias:
                        try:
                            suffix = old_user.split('.', 1)[1] if isinstance(old_user, str) and '.' in old_user else None
                        except Exception:
                            suffix = None
                        new_user = f"{alias}.{suffix}" if suffix else alias
                    else:
                        new_user = user_login
                    json_data['params'][0] = new_user
                    logger.info(f"authorize: old='{old_user}' -> new='{new_user}' (alias + preserved worker)")
                elif method == "mining.submit":
                    # Не переписываем worker; оставляем как есть, только логируем
                    if isinstance(params, list) and params:
                        worker_val = params[0]
                        logger.info(f"submit: worker stays='{worker_val}' (no rewrite)")
        return json.dumps(json_data)
    except Exception as e:
        logger.error(f"Ошибка при модификации логина/воркера: {e}")
        # Возвращаем исходные данные при ошибке
        try:
            if isinstance(data, bytes):
                return data.decode('utf-8', errors='ignore')
            return data.lstrip('\ufeff') if isinstance(data, str) else data
        except Exception:
            return data