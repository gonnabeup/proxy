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