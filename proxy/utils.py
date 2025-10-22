import logging
import json
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO"):
    """Настроить базовое логирование для прокси-модулей."""
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=lvl, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def safe_json_loads(text: str) -> Optional[dict]:
    """Безопасно парсит JSON-строку, возвращает dict или None."""
    try:
        return json.loads(text)
    except Exception:
        return None


def parse_login(login: str) -> Tuple[str, str]:
    """Разобрать строку логина вида 'user.worker' на (user, worker)."""
    if not isinstance(login, str):
        return "", ""
    if "." in login:
        u, w = login.split(".", 1)
        return u, w
    return login, ""


def is_time_in_range(current_time: str, start_time: str, end_time: str) -> bool:
    """
    Проверка, находится ли текущее время в диапазоне расписания.
    Вход: строки формата "HH:MM".
    Поддерживает диапазоны, пересекающие полночь.
    Особый случай: если start == end — считаем, что диапазон активен весь день.
    """
    def _to_minutes(t: str) -> Optional[int]:
        try:
            h, m = t.strip().split(":", 1)
            return int(h) * 60 + int(m)
        except Exception:
            return None

    cur = _to_minutes(current_time)
    start = _to_minutes(start_time)
    end = _to_minutes(end_time)

    if cur is None or start is None or end is None:
        logger.warning(f"Некорректный формат времени: current={current_time}, start={start_time}, end={end_time}")
        return False

    # Если старт и конец совпадают — трактуем как круглосуточный диапазон
    if start == end:
        return True

    if start < end:
        # Обычный диапазон в пределах суток
        return start <= cur <= end
    else:
        # Диапазон через полночь: например, 22:00–06:00
        return cur >= start or cur <= end