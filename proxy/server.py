import asyncio
import json
import logging
from typing import Dict, Set, Optional

from config.settings import PROXY_HOST
from db.models import init_db, get_session, User, Mode

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
        logger.info(f"Порт {port} остановлен")

    async def _handle_client(self, miner_reader: asyncio.StreamReader, miner_writer: asyncio.StreamWriter, port: int):
        addr = miner_writer.get_extra_info('peername')
        client_task = asyncio.current_task()
        self._clients.setdefault(port, set()).add(client_task)
        logger.info(f"Подключен майнер {addr} -> порт {port}")

        # Получаем пользователя и его активный режим
        session = get_session(self._engine)
        try:
            user = session.query(User).filter(User.port == port).first()
            if not user:
                logger.warning(f"Майнер {addr}: пользователь для порта {port} не найден. Закрываю.")
                miner_writer.close()
                await miner_writer.wait_closed()
                self._clients.get(port, set()).discard(client_task)
                return

            active_mode: Optional[Mode] = session.query(Mode).filter(Mode.user_id == user.id, Mode.is_active == 1).first()
            if not active_mode or active_mode.host.lower() in ("sleep", "сон") or active_mode.port == 0:
                logger.info(f"Майнер {addr}: активный режим 'sleep' для пользователя порт {port}. Закрываю соединение.")
                try:
                    # Нежно уведомим, если клиент ожидает JSON, но не обязательно
                    msg = {"id": None, "result": None, "error": {"code": -1, "message": "proxy sleep"}}
                    miner_writer.write((json.dumps(msg) + "\n").encode())
                    await miner_writer.drain()
                except Exception:
                    pass
                miner_writer.close()
                await miner_writer.wait_closed()
                self._clients.get(port, set()).discard(client_task)
                return

            host = active_mode.host
            upstream_port = active_mode.port
            alias_login = active_mode.alias
            logger.info(f"Майнер {addr}: подключаем к пулу {host}:{upstream_port} (mode={active_mode.name})")
        finally:
            session.close()

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
                    # Попробуем вытащить ошибку из ответа пула для диагностики
                    try:
                        resp_text = data.decode(errors='ignore').strip()
                        if resp_text:
                            resp = json.loads(resp_text)
                            err = resp.get("error")
                            if err:
                                logger.warning(f"Ответ пула с ошибкой для {addr} на порту {port}: {err}")
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
            logger.info(f"Соединение закрыто для {addr} на порту {port}")