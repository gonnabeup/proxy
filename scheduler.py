import asyncio
import logging
from datetime import datetime, time
from sqlalchemy import select

from db.models import User, Mode, Schedule, get_session
from proxy.utils import is_time_in_range

logger = logging.getLogger(__name__)

class Scheduler:
    def __init__(self, proxy_server, check_interval=60):
        """
        Инициализация планировщика
        
        :param proxy_server: Экземпляр прокси-сервера для обновления режимов
        :param check_interval: Интервал проверки расписаний в секундах
        """
        self.proxy_server = proxy_server
        self.check_interval = check_interval
        self.running = False
        self.task = None
        
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
            except Exception as e:
                logger.error(f"Ошибка при проверке расписаний: {e}")
                
            await asyncio.sleep(self.check_interval)
            
    async def _check_schedules(self):
        """Проверка расписаний и обновление активных режимов"""
        logger.debug("Проверка расписаний...")
        
        # Получаем текущее время
        now = datetime.now().time()
        
        # Создаем сессию БД
        db_session = get_session()
        try:
            # Получаем всех пользователей
            users = db_session.query(User).all()
            
            for user in users:
                # Получаем все расписания пользователя
                schedules = db_session.query(Schedule).filter(Schedule.user_id == user.id).all()
                
                # Проверяем каждое расписание
                for schedule in schedules:
                    # Преобразуем строки времени в объекты time
                    start_hour, start_minute = map(int, schedule.start_time.split(':'))
                    end_hour, end_minute = map(int, schedule.end_time.split(':'))
                    
                    start_time = time(start_hour, start_minute)
                    end_time = time(end_hour, end_minute)
                    
                    # Проверяем, находится ли текущее время в диапазоне расписания
                    if is_time_in_range(now, start_time, end_time):
                        # Если текущий активный режим не соответствует расписанию
                        if user.active_mode_id != schedule.mode_id:
                            logger.info(f"Обновление режима для пользователя {user.username} (ID: {user.id}) "
                                       f"согласно расписанию. Новый режим ID: {schedule.mode_id}")
                            
                            # Обновляем активный режим пользователя
                            user.active_mode_id = schedule.mode_id
                            db_session.commit()
                            
                            # Уведомляем прокси-сервер об изменении режима
                            if self.proxy_server:
                                await self.proxy_server.reload_port(user.port)
        
        finally:
            db_session.close()