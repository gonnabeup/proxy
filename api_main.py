import asyncio
import logging
import io
import sys
import datetime
from aiohttp import web
from sqlalchemy.orm import Session
from config.settings import (
    APP_API_HOST,
    APP_API_PORT,
    APP_API_TOKEN,
    DEFAULT_PORT_RANGE,
    PROXY_API_HOST,
    PROXY_API_PORT,
    PROXY_API_TOKEN,
    LOG_LEVEL,
)
from db.models import init_db, get_session, User, UserRole, Mode, Schedule, PaymentRequest, PaymentStatus

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='ignore')),
        logging.FileHandler('logs/api.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

engine = init_db()

async def auth(request: web.Request):
    t = APP_API_TOKEN or ""
    if t:
        if request.headers.get("X-Api-Token", "") != t:
            return web.json_response({"error": "unauthorized"}, status=401)
    return None

def json_error(msg: str, status: int = 400):
    return web.json_response({"error": msg}, status=status)

async def health(request: web.Request):
    err = await auth(request)
    if err:
        return err
    return web.json_response({"status": "ok"})

async def freerange(request: web.Request):
    err = await auth(request)
    if err:
        return err
    db: Session = get_session(engine)
    try:
        start, end = DEFAULT_PORT_RANGE
        used = {u.port for u in db.query(User).all()}
        free = [p for p in range(start, end + 1) if p not in used]
        return web.json_response({"free_ports": free})
    finally:
        db.close()

async def list_users(request: web.Request):
    err = await auth(request)
    if err:
        return err
    db: Session = get_session(engine)
    try:
        users = db.query(User).all()
        data = [
            {
                "id": u.id,
                "tg_id": int(u.tg_id),
                "username": u.username,
                "role": getattr(u.role, "value", str(u.role)),
                "port": u.port,
                "login": u.login,
                "timezone": u.timezone,
                "subscription_until": u.subscription_until.isoformat(),
            }
            for u in users
        ]
        return web.json_response({"users": data})
    finally:
        db.close()

async def add_user(request: web.Request):
    err = await auth(request)
    if err:
        return err
    body = await request.json()
    tg_id = int(body.get("tg_id"))
    username = body.get("username")
    port = int(body.get("port"))
    login = body.get("login")
    db: Session = get_session(engine)
    try:
        start, end = DEFAULT_PORT_RANGE
        if not (start <= port <= end):
            return json_error("port out of range")
        if db.query(User).filter((User.tg_id == tg_id) | (User.port == port)).first():
            return json_error("user or port exists")
        u = User(
            tg_id=tg_id,
            username=username,
            role=UserRole.USER,
            port=port,
            login=login,
            timezone='UTC',
            subscription_until=datetime.datetime.now().replace(microsecond=0) + datetime.timedelta(days=30),
        )
        db.add(u)
        db.flush()
        m = Mode(
            user_id=u.id,
            name='Sleep',
            host='sleep',
            port=0,
            alias='sleep',
            is_active=1,
        )
        db.add(m)
        db.commit()
        return web.json_response({"result": "created", "user_id": u.id})
    finally:
        db.close()

async def set_port(request: web.Request):
    err = await auth(request)
    if err:
        return err
    body = await request.json()
    tg_id = int(body.get("tg_id"))
    new_port = int(body.get("port"))
    db: Session = get_session(engine)
    try:
        start, end = DEFAULT_PORT_RANGE
        if not (start <= new_port <= end):
            return json_error("port out of range")
        if db.query(User).filter(User.port == new_port).first():
            return json_error("port busy")
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        old_port = u.port
        u.port = new_port
        db.commit()
        try:
            await proxy_reload_port(old_port)
        except Exception:
            pass
        try:
            await proxy_reload_port(new_port)
        except Exception:
            pass
        return web.json_response({"result": "updated", "old_port": old_port, "new_port": new_port})
    finally:
        db.close()

async def set_subscription(request: web.Request):
    err = await auth(request)
    if err:
        return err
    body = await request.json()
    tg_id = int(body.get("tg_id"))
    date_str = body.get("date")
    db: Session = get_session(engine)
    try:
        try:
            until = datetime.datetime.strptime(date_str, "%d.%m.%Y")
            until = until.replace(hour=23, minute=59, second=59, microsecond=0)
        except Exception:
            return json_error("bad date")
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        u.subscription_until = until
        db.commit()
        return web.json_response({"result": "updated"})
    finally:
        db.close()

async def extend_subscription(request: web.Request):
    err = await auth(request)
    if err:
        return err
    body = await request.json()
    tg_id = int(body.get("tg_id"))
    months = int(body.get("months", 1))
    db: Session = get_session(engine)
    try:
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        base = max(u.subscription_until, datetime.datetime.now().replace(microsecond=0))
        y = base.year
        m = base.month + months
        y += (m - 1) // 12
        m = ((m - 1) % 12) + 1
        d = min(base.day, (datetime.date(y, m, 1).replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)).day
        new_until = base.replace(year=y, month=m, day=d, hour=23, minute=59, second=59, microsecond=0)
        u.subscription_until = new_until
        db.commit()
        return web.json_response({"result": "updated", "until": new_until.isoformat()})
    finally:
        db.close()

async def list_modes(request: web.Request):
    err = await auth(request)
    if err:
        return err
    tg_id = int(request.match_info["tg_id"])
    db: Session = get_session(engine)
    try:
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        modes = db.query(Mode).filter(Mode.user_id == u.id).all()
        data = [{"id": m.id, "name": m.name, "host": m.host, "port": m.port, "alias": m.alias, "is_active": int(m.is_active)} for m in modes]
        return web.json_response({"modes": data})
    finally:
        db.close()

async def set_login(request: web.Request):
    err = await auth(request)
    if err:
        return err
    tg_id = int(request.match_info["tg_id"])
    body = await request.json()
    new_login = body.get("login")
    db: Session = get_session(engine)
    try:
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        u.login = new_login
        db.commit()
        return web.json_response({"result": "updated"})
    finally:
        db.close()

async def add_mode(request: web.Request):
    err = await auth(request)
    if err:
        return err
    tg_id = int(request.match_info["tg_id"])
    body = await request.json()
    name = body.get("name")
    host = body.get("host")
    port = int(body.get("port"))
    alias = body.get("alias")
    db: Session = get_session(engine)
    try:
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        m = Mode(user_id=u.id, name=name, host=host, port=port, alias=alias, is_active=0)
        db.add(m)
        db.commit()
        return web.json_response({"result": "created", "mode_id": m.id})
    finally:
        db.close()

async def activate_mode(request: web.Request):
    err = await auth(request)
    if err:
        return err
    tg_id = int(request.match_info["tg_id"])
    mode_id = int(request.match_info["mode_id"])
    db: Session = get_session(engine)
    try:
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        m = db.query(Mode).filter(Mode.id == mode_id, Mode.user_id == u.id).first()
        if not m:
            return json_error("mode not found", status=404)
        db.query(Mode).filter(Mode.user_id == u.id, Mode.is_active == 1).update({Mode.is_active: 0})
        m.is_active = 1
        db.commit()
        try:
            await proxy_reload_port(u.port)
        except Exception:
            pass
        return web.json_response({"result": "activated"})
    finally:
        db.close()

async def delete_mode(request: web.Request):
    err = await auth(request)
    if err:
        return err
    tg_id = int(request.match_info["tg_id"])
    mode_id = int(request.match_info["mode_id"])
    db: Session = get_session(engine)
    try:
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        m = db.query(Mode).filter(Mode.id == mode_id, Mode.user_id == u.id).first()
        if not m:
            return json_error("mode not found", status=404)
        db.delete(m)
        db.commit()
        return web.json_response({"result": "deleted"})
    finally:
        db.close()

async def list_schedules(request: web.Request):
    err = await auth(request)
    if err:
        return err
    tg_id = int(request.match_info["tg_id"])
    db: Session = get_session(engine)
    try:
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        schedules = db.query(Schedule).filter(Schedule.user_id == u.id).all()
        data = [{"id": s.id, "mode_id": s.mode_id, "start_time": s.start_time, "end_time": s.end_time} for s in schedules]
        return web.json_response({"schedules": data})
    finally:
        db.close()

async def add_schedule(request: web.Request):
    err = await auth(request)
    if err:
        return err
    tg_id = int(request.match_info["tg_id"])
    body = await request.json()
    mode_id = int(body.get("mode_id"))
    start_time = body.get("start_time")
    end_time = body.get("end_time")
    db: Session = get_session(engine)
    try:
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        m = db.query(Mode).filter(Mode.id == mode_id, Mode.user_id == u.id).first()
        if not m:
            return json_error("mode not found", status=404)
        s = Schedule(user_id=u.id, mode_id=m.id, start_time=start_time, end_time=end_time)
        db.add(s)
        db.commit()
        return web.json_response({"result": "created", "schedule_id": s.id})
    finally:
        db.close()

async def delete_schedule(request: web.Request):
    err = await auth(request)
    if err:
        return err
    tg_id = int(request.match_info["tg_id"])
    schedule_id = int(request.match_info["schedule_id"])
    db: Session = get_session(engine)
    try:
        u = db.query(User).filter(User.tg_id == tg_id).first()
        if not u:
            return json_error("user not found", status=404)
        s = db.query(Schedule).filter(Schedule.id == schedule_id, Schedule.user_id == u.id).first()
        if not s:
            return json_error("schedule not found", status=404)
        db.delete(s)
        db.commit()
        return web.json_response({"result": "deleted"})
    finally:
        db.close()

async def list_payments(request: web.Request):
    err = await auth(request)
    if err:
        return err
    db: Session = get_session(engine)
    try:
        prs = db.query(PaymentRequest).filter(PaymentRequest.status == PaymentStatus.PENDING).order_by(PaymentRequest.created_at.asc()).all()
        data = [{"id": pr.id, "user_id": pr.user_id, "method": getattr(pr.method, "value", str(pr.method)), "file_id": pr.file_id, "created_at": pr.created_at.isoformat()} for pr in prs]
        return web.json_response({"requests": data})
    finally:
        db.close()

async def payment_update(request: web.Request):
    err = await auth(request)
    if err:
        return err
    body = await request.json()
    req_id = int(body.get("id"))
    action = body.get("action")
    db: Session = get_session(engine)
    try:
        pr = db.query(PaymentRequest).filter(PaymentRequest.id == req_id).first()
        if not pr:
            return json_error("request not found", status=404)
        if action == "approve":
            pr.status = PaymentStatus.APPROVED
        elif action == "reject":
            pr.status = PaymentStatus.REJECTED
        else:
            return json_error("bad action")
        db.commit()
        return web.json_response({"result": "updated"})
    finally:
        db.close()

async def proxy_reload(request: web.Request):
    err = await auth(request)
    if err:
        return err
    body = await request.json()
    port = int(body.get("port"))
    await proxy_reload_port(port)
    return web.json_response({"result": "reloaded", "port": port})

async def proxy_reload_port(port: int):
    import aiohttp
    base = f"http://{PROXY_API_HOST}:{PROXY_API_PORT}"
    url = base + "/reload-port"
    headers = {"X-Proxy-Token": PROXY_API_TOKEN} if PROXY_API_TOKEN else {}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"port": port}, headers=headers) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(f"proxy api error {resp.status}: {text}")

def build_app():
    app = web.Application()
    app.add_routes([
        web.get("/health", health),
        web.get("/freerange", freerange),
        web.get("/users", list_users),
        web.post("/admin/add-user", add_user),
        web.post("/admin/set-port", set_port),
        web.post("/admin/set-subscription", set_subscription),
        web.post("/admin/extend-subscription", extend_subscription),
        web.get("/users/{tg_id}/modes", list_modes),
        web.post("/users/{tg_id}/set-login", set_login),
        web.post("/users/{tg_id}/modes", add_mode),
        web.post("/users/{tg_id}/modes/{mode_id}/activate", activate_mode),
        web.delete("/users/{tg_id}/modes/{mode_id}", delete_mode),
        web.get("/users/{tg_id}/schedules", list_schedules),
        web.post("/users/{tg_id}/schedules", add_schedule),
        web.delete("/users/{tg_id}/schedules/{schedule_id}", delete_schedule),
        web.get("/admin/payments", list_payments),
        web.post("/admin/payment-update", payment_update),
        web.post("/proxy/reload-port", proxy_reload),
    ])
    return app

async def main():
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, APP_API_HOST, APP_API_PORT)
    await site.start()
    stop_event = asyncio.Event()
    await stop_event.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("API остановлено пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка API: {e}", exc_info=True)