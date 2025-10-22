import logging

logger = logging.getLogger(__name__)


def _to_minutes(hhmm: str) -> int:
    try:
        parts = hhmm.split(":")
        if len(parts) != 2:
            raise ValueError("bad format")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("out of range")
        return h * 60 + m
    except Exception:
        logger.warning(f"Неверный формат времени: '{hhmm}', ожидается 'HH:MM'")
        return -1


def is_time_in_range(current_time: str, start_time: str, end_time: str) -> bool:
    """
    Проверяет, входит ли текущее время ("HH:MM") в диапазон [start_time, end_time],
    корректно обрабатывая диапазоны, пересекающие полночь. Если start_time == end_time,
    трактуется как круглосуточный диапазон (всегда True).
    """
    cur = _to_minutes(current_time)
    start = _to_minutes(start_time)
    end = _to_minutes(end_time)

    # Если формат неверный — безопасно вернуть False
    if cur < 0 or start < 0 or end < 0:
        return False

    # Круглосуточно
    if start == end:
        return True

    if start < end:
        # Обычный диапазон в пределах суток
        return start <= cur <= end
    else:
        # Диапазон через полночь: например 22:00–06:00
        return cur >= start or cur <= end


__all__ = ["is_time_in_range"]