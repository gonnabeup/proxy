import asyncio
import json
import logging
import datetime
import re
from typing import Dict, Set, Optional

from aiogram import Bot
from aiogram.enums import ParseMode
from config.settings import PROXY_HOST, BOT_TOKEN
from db.models import init_db, get_session, User, Mode, Device

logger = logging.getLogger(__name__)


class StratumProxyServer:
    """
    Многопользовательский Stratum-прокси.
    - Для каждого пользователя поднимаем TCP-сервер на его уникальном порту.
    - Для каждого входящего соединения определяем активный режим пользователя и
      проксируем трафик к соответствующему пулу.
    - Перехватываем и переписываем "mining.authorize" так, чтобы логин майнера
      (User.login[.worker]) заменялся на логин/кошелёк пула (Mode.alias[.worker]).
    - Предоставляем reload_port(port) для точечной перезагрузки порта после изменения режима/настроек.
    """

    def __init__(self, host: str = PROXY_HOST):
        self.host = host
        self._engine = init_db()
        self._servers: Dict[int, asyncio.AbstractServer] = {}
        self._clients: Dict[int, Set[asyncio.Task]] = {}
        # Учёт занятых воркеров по порту: базовая строка alias[.worker] -> счётчик
        self._active_workers: Dict[int, Dict[asyncio.Task, str]] = {}
        self._worker_counts: Dict[int, Dict[str, int]] = {}
        self._port_mode: Dict[int, dict] = {}
        self._lock = asyncio.Lock()

    async def start(self):
        """Запускает серверы для всех пользователей из БД."""
        logger.info("Инициализация StratumProxyServer...")
        session = get_session(self._engine)
        try:
            users = session.query(User).all()
            if not users:
                logger.warning("В БД нет пользователей. Прокси серверы не запущены.")
                return
            for user in users:
                await self._start_port(user.port)
            logger.info(f"Запущено портов: {len(self._servers)}")
        finally:
            session.close()

    async def stop(self):
        """Останавливает все серверы и активные клиентские соединения."""
        logger.info("Остановка всех портов прокси...")
        # Копии ключей, чтобы безопасно итерироваться
        for port in list(self._servers.keys()):
            await self._stop_port(port)
        logger.info("Прокси-сервер остановлен")

    async def reload_port(self, port: int):
        """Точечная перезагрузка сервера на указанном порту."""
        async with self._lock:
            logger.info(f"Перезагрузка порта {port}...")
            await self._stop_port(port)
            await self._start_port(port)
            logger.info(f"Порт {port} перезагружен")

    async def _start_port(self, port: int):
        """Запуск прослушивания указанного порта, если для него существует пользователь."""
        session = get_session(self._engine)
        try:
            user = session.query(User).filter(User.port == port).first()
            if not user:
                logger.warning(f"Пользователь для порта {port} не найден. Пропускаю запуск.")
                return
            active_mode: Optional[Mode] = session.query(Mode).filter(Mode.user_id == user.id, Mode.is_active == 1).first()
            if active_mode:
                self._port_mode[port] = {
                    "host": active_mode.host,
                    "port": active_mode.port,
                    "alias": active_mode.alias,
                    "mode_name": active_mode.name,
                    "login": user.login,
                }
            else:
                self._port_mode[port] = {
                    "host": "sleep",
                    "port": 0,
                    "alias": "",
                    "mode_name": "sleep",
                    "login": user.login,
                }
        finally:
            session.close()

        # Уже запущен
        if port in self._servers:
            logger.info(f"Порт {port} уже запущен. Пропускаю старт.")
            return

        server = await asyncio.start_server(lambda r, w: self._handle_client(r, w, port), self.host, port)
        self._servers[port] = server
        self._clients.setdefault(port, set())
        addr = server.sockets[0].getsockname() if server.sockets else (self.host, port)
        logger.info(f"Слушаю {addr} для пользователя порта {port}")

    async def _stop_port(self, port: int):
        """Остановка прослушивания порта и завершение клиентских соединений."""
        # Закрыть сервер
        server = self._servers.pop(port, None)
        if server:
            try:
                server.close()
                await server.wait_closed()
            except Exception as e:
                logger.warning(f"Ошибка при закрытии сервера порта {port}: {e}")
        
        # Отменить активные клиентские задачи
        tasks = self._clients.pop(port, set())
        for t in list(tasks):
            try:
                t.cancel()
            except Exception:
                pass
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception:
                pass
        # Очистить учёт воркеров
        self._active_workers.pop(port, None)
        self._worker_counts.pop(port, None)
        self._port_mode.pop(port, None)
        logger.info(f"Порт {port} остановлен")

    async def _handle_client(self, miner_reader: asyncio.StreamReader, miner_writer: asyncio.StreamWriter, port: int):
        addr = miner_writer.get_extra_info('peername')
        client_task = asyncio.current_task()
        self._clients.setdefault(port, set()).add(client_task)
        logger.info(f"Подключен майнер {addr} -> порт {port}")

        # Получаем активный режим из кеша порта (без запросов к БД)
        cached = self._port_mode.get(port)
        if not cached or cached.get("mode_name") == "sleep" or not cached.get("host") or int(cached.get("port", 0)) == 0:
            logger.info(f"Майнер {addr}: активный режим 'sleep' для пользователя порт {port}. Закрываю соединение.")
            try:
                msg = {"id": None, "result": None, "error": {"code": -1, "message": "proxy sleep"}}
                miner_writer.write((json.dumps(msg) + "\n").encode())
                await miner_writer.drain()
            except Exception:
                pass
            miner_writer.close()
            await miner_writer.wait_closed()
            self._clients.get(port, set()).discard(client_task)
            return

        host = cached.get("host")
        upstream_port = int(cached.get("port"))
        alias_login = cached.get("alias", "")
        logger.info(f"Майнер {addr}: подключаем к пулу {host}:{upstream_port} (mode={cached.get('mode_name')})")

        # Подключаемся к пулу
        try:
            pool_reader, pool_writer = await asyncio.open_connection(host, upstream_port)
        except Exception as e:
            logger.error(f"Майнер {addr}: не удалось подключиться к пулу {host}:{upstream_port}: {e}")
            miner_writer.close()
            try:
                await miner_writer.wait_closed()
            except Exception:
                pass
            self._clients.get(port, set()).discard(client_task)
            return

        # Счётчики ошибок пула на время данного соединения
        error_counts = {}

        async def forward_to_pool():
            try:
                while not miner_reader.at_eof():
                    data = await miner_reader.readline()
                    if not data:
                        break
                    text = data.decode(errors='ignore').strip()
                    if not text:
                        continue
                    try:
                        msg = json.loads(text)
                    except json.JSONDecodeError:
                        # Непарсибельное — отправляем как есть
                        pool_writer.write(data)
                        await pool_writer.drain()
                        continue

                    method = msg.get("method")
                    if method == "mining.authorize":
                        params = msg.get("params", [])
                        # Используем alias_login из активного режима, полученного при подключении
                        # Режимы обновляются через reload_port, который перезапускает сервер

                        if params and isinstance(params[0], str) and alias_login:
                            original = params[0]
                            if "." in original:
                                miner_login, worker = original.split(".", 1)
                            else:
                                miner_login, worker = original, ""

                            # Базовое желаемое имя (без уникализации)
                            base_desired = f"{alias_login}.{worker}" if worker else alias_login

                            # Учёт уникальности воркеров на порту
                            counts = self._worker_counts.setdefault(port, {})
                            active_map = self._active_workers.setdefault(port, {})
                            prev_base = active_map.get(client_task)
                            if prev_base and prev_base != base_desired:
                                # клиент сменил воркера — скорректируем счётчики
                                prev_count = counts.get(prev_base, 0)
                                if prev_count > 1:
                                    counts[prev_base] = prev_count - 1
                                elif prev_count == 1:
                                    counts.pop(prev_base, None)

                            usage = counts.get(base_desired, 0) + 1
                            counts[base_desired] = usage
                            active_map[client_task] = base_desired

                            if usage == 1:
                                new_user = base_desired
                            else:
                                # Добавляем суффикс -2, -3... чтобы пул не разрывал первое соединение
                                if worker:
                                    new_user = f"{alias_login}.{worker}-{usage}"
                                else:
                                    new_user = f"{alias_login}-{usage}"

                            msg["params"][0] = new_user
                            data = (json.dumps(msg) + "\n").encode()
                            logger.info(f"Порт {port}: authorize {original} -> {new_user}")

                            # === Апсерть устройства в БД ===
                            try:
                                session = get_session(self._engine)
                                u = session.query(User).filter(User.port == port).first()
                                if u:
                                    worker_key = worker or ""
                                    # имя устройства по умолчанию — воркер
                                    name_val = worker_key or None
                                    # попытка извлечь числовой идентификатор воркера (например, b11 -> 11)
                                    m = re.search(r"(\d+)$", worker_key) if worker_key else None
                                    worker_number = int(m.group(1)) if m else None
                                    now = datetime.datetime.utcnow()
                                    dev = session.query(Device).filter(Device.user_id == u.id, Device.worker == worker_key).first()
                                    if dev:
                                        if not dev.name:
                                            dev.name = name_val
                                        dev.last_connected_at = now
                                        dev.last_seen_at = now
                                        dev.is_online = 1
                                    else:
                                        dev = Device(
                                            user_id=u.id,
                                            worker=worker_key,
                                            worker_number=worker_number,
                                            name=name_val,
                                            last_connected_at=now,
                                            last_seen_at=now,
                                            is_online=1,
                                        )
                                        session.add(dev)
                                    session.commit()
                                session.close()
                            except Exception as e:
                                logger.warning(f"Не удалось обновить Device для порта {port}: {e}")
                        else:
                            # Если нет params или alias пуст, отправляем как есть
                            data = (json.dumps(msg) + "\n").encode()

                        pool_writer.write(data)
                        await pool_writer.drain()
                        continue

                    # Иные сообщения — транзит
                    pool_writer.write((json.dumps(msg) + "\n").encode())
                    await pool_writer.drain()
            except asyncio.CancelledError:
                pass
            except (ConnectionResetError, BrokenPipeError):
                logger.info(f"Пул закрыл соединение для {addr} на порту {port}")
            except Exception as e:
                logger.error(f"Ошибка форвардинга к пулу для {addr}: {e}")
            finally:
                try:
                    pool_writer.close()
                    await pool_writer.wait_closed()
                except Exception:
                    pass

        async def forward_to_miner():
            try:
                while not pool_reader.at_eof():
                    data = await pool_reader.readline()
                    if not data:
                        break
                    # Диагностика ответов пула: отличаем нормальные ошибки (stale/unknown) от проблемных
                    try:
                        resp_text = data.decode(errors='ignore').strip()
                        if resp_text:
                            resp = json.loads(resp_text)
                            err = resp.get("error")
                            if err is not None:
                                # Stratum обычно возвращает [code, message, data]
                                code = None
                                message = None
                                if isinstance(err, list) and len(err) >= 2:
                                    code, message = err[0], err[1]
                                elif isinstance(err, dict):
                                    code = err.get("code")
                                    message = err.get("message")
                                m = str(message) if message is not None else str(err)
                                if m in ("stale-work", "unknown-work"):
                                    logger.info(f"Ответ пула: {m} для {addr} на порту {port} (code={code})")
                                else:
                                    logger.warning(f"Ответ пула с ошибкой для {addr} на порту {port}: {err}")
                                # Счётчики на соединение
                                key = m or "error"
                                error_counts[key] = error_counts.get(key, 0) + 1
                    except Exception:
                        pass

                    miner_writer.write(data)
                    await miner_writer.drain()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Ошибка форвардинга к майнеру для {addr}: {e}")
            finally:
                try:
                    miner_writer.close()
                    await miner_writer.wait_closed()
                except Exception:
                    pass

        try:
            await asyncio.gather(forward_to_pool(), forward_to_miner())
        finally:
            self._clients.get(port, set()).discard(client_task)
            # Корректировка счётчиков воркеров на порту
            active_map = self._active_workers.get(port)
            counts = self._worker_counts.get(port)
            if active_map is not None and counts is not None:
                base = active_map.pop(client_task, None)
                if base:
                    c = counts.get(base, 0)
                    if c > 1:
                        counts[base] = c - 1
                    elif c == 1:
                        counts.pop(base, None)
                        # Отмечаем устройство оффлайн, если это было последнее соединение данного воркера
                        try:
                            session = get_session(self._engine)
                            u = session.query(User).filter(User.port == port).first()
                            if u:
                                worker_part = base.split('.', 1)[1] if '.' in base else ''
                                if worker_part:
                                    worker_part = re.sub(r'-\d+$', '', worker_part)
                                dev = session.query(Device).filter(Device.user_id == u.id, Device.worker == worker_part).first()
                                if dev:
                                    dev.is_online = 0
                                    dev.last_seen_at = datetime.datetime.utcnow()
                                    session.commit()
                                    # Попробуем отправить уведомление пользователю о отключении устройства
                                    try:
                                        if BOT_TOKEN and getattr(u, "tg_id", None):
                                            bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
                                            name = dev.name or dev.worker or "Аппарат"
                                            worker_info = f" ({dev.worker})" if dev.worker else ""
                                            text = f"❗️ {name}{worker_info} стал оффлайн."
                                            await bot.send_message(chat_id=u.tg_id, text=text)
                                            await bot.session.close()
                                    except Exception as e:
                                        logger.warning(f"Ошибка отправки уведомления об оффлайне: {e}")
                            session.close()
                        except Exception as e:
                            logger.warning(f"Не удалось отметить оффлайн Device для порта {port}: {e}")
            # Итоговая статистика ошибок пула по данному соединению
            if error_counts:
                try:
                    summary = ", ".join(f"{k}={v}" for k, v in error_counts.items())
                    logger.info(f"Итог по ошибкам пула для {addr} на порту {port}: {summary}")
                except Exception:
                    pass
            logger.info(f"Соединение закрыто для {addr} на порту {port}")