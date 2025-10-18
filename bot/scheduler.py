import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db.models import User, Mode, Schedule, get_session, init_db
from proxy.utils import is_time_in_range

logger = logging.getLogger(__name__)

class Scheduler:
    def __init__(self, proxy_server, check_interval=60, bot=None):
        """
        Инициализация планировщика
        
        :param proxy_server: Экземпляр прокси-сервера для обновления режимов
        :param check_interval: Интервал проверки расписаний в секундах
        :param bot: Экземпляр Telegram-бота для уведомлений (опционально)
        """
        self.proxy_server = proxy_server
        self.check_interval = check_interval
        self.bot = bot
        self.running = False
        self.task = None
        # Защита от повторных уведомлений в течение одного дня
        # Формат: {user_id: {date: set(days_left)}}
        self._notified_today = {}
        
    async def start(self):
        """Запуск планировщика"""
        if self.running:
            return
            
        self.running = True
        self.task = asyncio.create_task(self._scheduler_loop())
        logger.info("Планировщик запущен")
        
    async def stop(self):
        """Остановка планировщика"""
        if not self.running:
            return
            
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("Планировщик остановлен")
        
    async def _scheduler_loop(self):
        """Основной цикл планировщика"""
        while self.running:
            try:
                await self._check_schedules()
                await self._check_subscription_reminders()
            except Exception as e:
                logger.error(f"Ошибка при проверке расписаний: {e}")
                
            await asyncio.sleep(self.check_interval)
            
    async def _check_schedules(self):
        """Проверка расписаний и обновление активных режимов"""
        logger.debug("Проверка расписаний...")
        changed_ports = set()
        
        # Текущее время вычисляется для каждого пользователя в его часовом поясе
        
        # Создаем engine и сессию БД
        engine = init_db()
        db_session = get_session(engine)
        try:
            # Получаем всех пользователей
            users = db_session.query(User).all()
            
            for user in users:
                # Получаем все расписания пользователя
                schedules = db_session.query(Schedule).filter(Schedule.user_id == user.id).all()
                
                # Проверяем каждое расписание
                for schedule in schedules:
                    # Определяем локальное время пользователя
                    tz_name = user.timezone or "Europe/Moscow"
                    current_time = datetime.now(ZoneInfo(tz_name)).strftime("%H:%M")
                    # Проверяем, находится ли текущее время в диапазоне расписания (строки HH:MM)
                    if is_time_in_range(current_time, schedule.start_time, schedule.end_time):
                        # Текущий активный режим пользователя
                        active_mode = db_session.query(Mode).filter(Mode.user_id == user.id, Mode.is_active == 1).first()
                        # Если текущий активный режим не соответствует расписанию
                        if not active_mode or active_mode.id != schedule.mode_id:
                            logger.info(f"Обновление режима для пользователя {user.username} (ID: {user.id}) "
                                       f"согласно расписанию. Новый режим ID: {schedule.mode_id}")

                            # Снимаем активность у предыдущего режима и активируем режим из расписания
                            db_session.query(Mode).filter(Mode.user_id == user.id, Mode.is_active == 1).update({Mode.is_active: 0})
                            mode_to_activate = db_session.query(Mode).filter(Mode.id == schedule.mode_id, Mode.user_id == user.id).first()
                            if mode_to_activate:
                                mode_to_activate.is_active = 1
                                db_session.commit()
                                # Запомним порт пользователя, которому нужна перезагрузка
                                changed_ports.add(user.port)
            # Точечная перезагрузка портов, где были изменения
            if self.proxy_server and changed_ports:
                for port in changed_ports:
                    await self.proxy_server.reload_port(port)
        
        finally:
            db_session.close()

    async def _check_subscription_reminders(self):
        """Отправка уведомлений пользователям за 3, 2 и 1 день до окончания подписки"""
        if self.bot is None:
            return
        logger.debug("Проверка напоминаний о подписке...")

        engine = init_db()
        db_session = get_session(engine)
        try:
            users = db_session.query(User).all()
            for user in users:
                # Дата в часовом поясе пользователя
                tz_name = user.timezone or "Europe/Moscow"
                today_user = datetime.now(ZoneInfo(tz_name)).date()
                expiry_date = user.subscription_until.date()

                days_left = (expiry_date - today_user).days
                if days_left in (3, 2, 1):
                    notified_for_date = self._notified_today.setdefault(user.id, {})
                    notified_set = notified_for_date.setdefault(today_user, set())
                    if days_left in notified_set:
                        continue

                    if days_left == 1:
                        prefix = "Ваша подписка заканчивается завтра"
                    elif days_left == 2:
                        prefix = "Ваша подписка заканчивается через 2 дня"
                    else:
                        prefix = "Ваша подписка заканчивается через 3 дня"

                    message = (
                        f"⚠️ Напоминание\n"
                        f"{prefix} (до {user.subscription_until.strftime('%d.%m.%Y %H:%M')}).\n\n"
                        f"Чтобы продлить, нажмите кнопку ниже."
                    )
                    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Оплатить", callback_data="pay_open")]])
                    try:
                        await self.bot.send_message(chat_id=user.tg_id, text=message, reply_markup=kb)
                        notified_set.add(days_left)
                        logger.info(f"Отправлено напоминание ({days_left} дн.) пользователю {user.username} (ID: {user.id})")
                    except Exception as e:
                        logger.error(f"Ошибка отправки напоминания пользователю {user.username} (ID: {user.id}): {e}")
        finally:
            db_session.close()