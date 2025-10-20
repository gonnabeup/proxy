import logging
import asyncio
from sqlalchemy.orm import Session
import sys
import os
import json
import binascii

# Добавляем корневую директорию в путь для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import User, Mode
from proxy.utils import get_user_by_port, get_active_mode, get_scheduled_mode
from proxy.utils import modify_stratum_credentials

logger = logging.getLogger(__name__)

class StratumRouter:
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.connections = {}  # Словарь для хранения активных соединений

    async def update_active_modes_by_schedule(self):
        """Обновление активных режимов пользователей согласно их расписаниям.
        Использует локальное время пользователя через get_scheduled_mode.
        """
        try:
            users = self.db_session.query(User).all()
            for user in users:
                scheduled_mode = get_scheduled_mode(self.db_session, user.id)
                if scheduled_mode:
                    active_mode = self.db_session.query(Mode).filter(Mode.user_id == user.id, Mode.is_active == 1).first()
                    if not active_mode or active_mode.id != scheduled_mode.id:
                        # Деактивируем предыдущие и активируем расписанный режим
                        self.db_session.query(Mode).filter(Mode.user_id == user.id, Mode.is_active == 1).update({Mode.is_active: 0})
                        scheduled_mode.is_active = 1
                        self.db_session.commit()
                        logger.info(
                            f"Активирован режим по расписанию для пользователя {user.username} (ID: {user.id}). "
                            f"Новый режим ID: {scheduled_mode.id}"
                        )
        except Exception as e:
            logger.error(f"Ошибка при обновлении режимов по расписанию: {e}")
    
    async def handle_client(self, reader, writer, client_port):
        """Обработка подключения клиента"""
        client_addr = writer.get_extra_info('peername')
        logger.info(f"Новое подключение от {client_addr} на порт {client_port}")
        
        # Получаем пользователя по порту
        user = get_user_by_port(self.db_session, client_port)
        if not user:
            logger.warning(f"Пользователь для порта {client_port} не найден")
            writer.close()
            await writer.wait_closed()
            return
        
        # Проверяем активность подписки
        if not user.is_subscription_active():
            logger.warning(f"Подписка пользователя {user.username} (ID: {user.id}) истекла")
            try:
                writer.write("Подписка истекла. Обратитесь к администратору.\n".encode("utf-8"))
                await writer.drain()
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения: {e}")
            finally:
                writer.close()
                await writer.wait_closed()
            return
        
        # Определяем активный режим (по расписанию или вручную установленный)
        mode = get_scheduled_mode(self.db_session, user.id) or get_active_mode(self.db_session, user.id)

        if not mode:
            logger.warning(f"Активный режим для пользователя {user.username} (ID: {user.id}) не найден")
            try:
                writer.write("Режим не настроен. Установите режим через Telegram-бот.\n".encode("utf-8"))
                await writer.drain()
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения: {e}")
            finally:
                writer.close()
                await writer.wait_closed()
            return

        # Если активен режим Sleep — не подключаемся к пулу, а закрываем соединение
        if (mode.name or '').lower() == 'sleep' or (mode.host or '').lower() == 'sleep':
            logger.info(f"Подключение на порт {client_port} для пользователя {user.username} отклонено: активен режим Sleep")
            try:
                writer.write("Порт в режиме сна. Активируйте рабочий режим через /setmode.\n".encode("utf-8"))
                await writer.drain()
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения о режиме сна: {e}")
            finally:
                writer.close()
                await writer.wait_closed()
            return
        
        # Подключаемся к пулу
        try:
            pool_reader, pool_writer = await asyncio.open_connection(mode.host, mode.port)
            logger.info(f"Подключено к пулу {mode.host}:{mode.port} для пользователя {user.username}")
            logger.info(f"Параметры режима: login='{user.login}', alias='{mode.alias}', user_port={client_port}, pool={mode.host}:{mode.port}")
            
            # Сохраняем информацию о соединении
            connection_info = {
                'user': user,
                'mode': mode,
                'client_reader': reader,
                'client_writer': writer,
                'pool_reader': pool_reader,
                'pool_writer': pool_writer,
                'port': client_port
            }
            
            self.connections[client_addr] = connection_info
            
            # Запускаем две задачи для проксирования данных в обе стороны
            client_to_pool_task = asyncio.create_task(
                self._proxy_data(reader, pool_writer, user.login, mode.alias, 'client->pool')
            )
            
            pool_to_client_task = asyncio.create_task(
                self._proxy_data(pool_reader, writer, None, None, 'pool->client')
            )
            
            # Ждем завершения любой из задач
            done, pending = await asyncio.wait(
                [client_to_pool_task, pool_to_client_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Отменяем оставшуюся задачу
            for task in pending:
                task.cancel()
                
            # Закрываем соединения
            writer.close()
            pool_writer.close()
            await writer.wait_closed()
            await pool_writer.wait_closed()
            
            # Удаляем информацию о соединении
            if client_addr in self.connections:
                del self.connections[client_addr]
                
        except Exception as e:
            logger.error(f"Ошибка при подключении к пулу {mode.host}:{mode.port}: {e}")
            try:
                writer.write(f"Ошибка подключения к пулу: {str(e)}\n".encode())
                await writer.drain()
            except Exception as e:
                logger.error(f"Ошибка при отправке сообщения об ошибке: {e}")
            finally:
                writer.close()
                await writer.wait_closed()

    async def _proxy_data(self, reader, writer, login, alias, direction):
        """Проксирование данных между клиентом и пулом"""
        tls_warned = False
        try:
            while not reader.at_eof():
                data = await reader.read(8192)
                if not data:
                    break
                
                # Диагностика: размер чанка
                logger.debug(f"Чанк {direction}: {len(data)} байт")

                # Всегда пытаемся модифицировать authorize/submit, когда идём от клиента к пулу
                if direction == 'client->pool' and (login or alias):
                    # Детект TLS: первые байты TLS-записи 0x16 0x03
                    try:
                        if isinstance(data, (bytes, bytearray)) and len(data) >= 2 and data[0] == 0x16 and data[1] == 0x03:
                            if not tls_warned:
                                head_hex = binascii.hexlify(data[:16]).decode('ascii')
                                logger.info(
                                    f"Обнаружен TLS/SSL-трафик от клиента (hex: {head_hex}). "
                                    f"Подмена логина/воркера невозможна без TLS-терминации. "
                                    f"Рекомендуется настроить пул на не-SSL порт (например 3333)."
                                )
                                tls_warned = True
                            # В TLS режимах не трогаем данные
                        else:
                            # Попытка декодировать для выявления JSON (Stratum)
                            text = data.decode('utf-8', errors='ignore')
                            stripped = text.strip()
                            looks_json = stripped.startswith('{') or stripped.startswith('[')
                            has_stratum = ('"method"' in text) or ('mining.' in text)

                            if looks_json and has_stratum:
                                # Логируем исходный метод и params[0]
                                try:
                                    first_line = stripped.splitlines()[0]
                                    obj = json.loads(first_line)
                                    method = obj.get('method')
                                    params = obj.get('params')
                                    p0 = params[0] if isinstance(params, list) and params else None
                                    logger.info(f"Стратум-запрос: {method}, params[0]={p0}")
                                except Exception as ex:
                                    logger.debug(f"Не удалось разобрать JSON для логирования: {ex}")

                                try:
                                    modified_text = modify_stratum_credentials(text, login or '', alias or '')
                                    if modified_text != text:
                                        # Выводим краткое резюме подмены
                                        logger.info(
                                            f"Подмена кредов выполнена: login='{login}' alias='{alias}'"
                                        )
                                    data = modified_text.encode('utf-8')
                                except Exception as ex:
                                    logger.warning(f"Ошибка при попытке подмены кредов: {ex}")
                                    # Оставляем оригинальные байты
                            else:
                                # Не JSON — выводим первые байты для диагностики
                                head_hex = binascii.hexlify(data[:32]).decode('ascii')
                                logger.debug(f"{direction}: не-JSON поток (hex head {head_hex}) — оставляем без изменений")
                    except Exception as log_ex:
                        logger.debug(f"Логирование/детекция клиента не выполнено: {log_ex}")
                
                # Отправляем дальше
                out_bytes = data if isinstance(data, (bytes, bytearray)) else str(data).encode('utf-8')
                writer.write(out_bytes)
                await writer.drain()
                
        except asyncio.CancelledError:
            # Задача была отменена, это нормальное поведение
            pass
        except Exception as e:
            logger.error(f"Ошибка при проксировании данных ({direction}): {e}")
    
    def close_all_connections(self):
        """Закрытие всех активных соединений"""
        for client_addr, conn_info in self.connections.items():
            try:
                conn_info['client_writer'].close()
                conn_info['pool_writer'].close()
            except Exception as e:
                logger.error(f"Ошибка при закрытии соединения {client_addr}: {e}")
        
        self.connections.clear()

    def close_connections_by_port(self, port: int):
        """Закрытие активных соединений только для указанного порта"""
        to_close = []
        for client_addr, conn_info in self.connections.items():
            try:
                if conn_info.get('port') == port:
                    conn_info['client_writer'].close()
                    conn_info['pool_writer'].close()
                    to_close.append(client_addr)
            except Exception as e:
                logger.error(f"Ошибка при закрытии соединения {client_addr} для порта {port}: {e}")
        for client_addr in to_close:
            self.connections.pop(client_addr, None)