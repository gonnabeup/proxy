from .user_commands import register_user_handlers
from .admin_commands import register_admin_handlers
from aiogram import F, Bot
from aiogram.types import ChatMemberUpdated
import logging

logger = logging.getLogger(__name__)

async def _guard_leave_non_private(event: ChatMemberUpdated, bot: Bot):
    chat = event.chat
    if getattr(chat, "type", None) != "private":
        try:
            await bot.leave_chat(chat_id=chat.id)
            logger.info(f"Покинул чат {chat.id} ({chat.type}) по авто-правилу")
        except Exception as e:
            logger.warning(f"Не удалось покинуть чат {chat.id} ({chat.type}): {e}")


def register_handlers(dp, proxy_server=None):
    """Регистрация всех обработчиков бота
    proxy_server: экземпляр StratumProxyServer для операций перезагрузки портов.
    """
    # Ограничиваем обработку только приватными чатами
    dp.message.filter(F.chat.type == "private")
    dp.callback_query.filter(F.message.chat.type == "private")
    
    # Авто-выход из групп и каналов при добавлении бота
    dp.my_chat_member.filter(F.chat.type != "private")
    dp.my_chat_member.register(_guard_leave_non_private)
    
    register_user_handlers(dp)
    # Передаём proxy_server в админские обработчики, если доступен
    register_admin_handlers(dp, proxy_server=proxy_server)