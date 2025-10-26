from aiogram import Dispatcher, types, F
from aiogram.fsm.context import FSMContext

from db.models import User, Mode, get_session, init_db, UserRole, Device
from bot.keyboards import (
    get_pools_management_keyboard,
    get_settings_keyboard,
    get_delete_modes_keyboard,
    get_main_keyboard,
    get_back_keyboard,
)
from .user_commands import cmd_addmode, cmd_modes

import logging
logger = logging.getLogger(__name__)
from datetime import datetime

def _is_admin_user(user) -> bool:
    try:
        if not user:
            return False
        role = getattr(user, "role", None)
        if role is None:
            return False
        if isinstance(role, str):
            return role.upper() in ("ADMIN", "SUPERADMIN")
        return role in (UserRole.ADMIN, UserRole.SUPERADMIN)
    except Exception:
        return False


# ===== Разделы меню =====
async def cmd_pool_management(message: types.Message):
    await message.answer("Выберите действие:", reply_markup=get_pools_management_keyboard())


async def cmd_settings(message: types.Message):
    await message.answer("Выберите настройку:", reply_markup=get_settings_keyboard())


async def cmd_back(message: types.Message, state: FSMContext):
    engine = init_db()
    db_session = get_session(engine)
    try:
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        is_admin = _is_admin_user(user)
        data = await state.get_data()
        dest = data.get("back_to")
        if dest == "pools_management":
            await state.update_data(back_to=None)
            await message.answer("Меню управления пулами:", reply_markup=get_pools_management_keyboard())
        else:
            await message.answer("Главное меню:", reply_markup=get_main_keyboard(is_admin=is_admin))
    finally:
        db_session.close()


# ===== Удаление пулов с пагинацией =====
async def cmd_delete_mode_start(message: types.Message, state: FSMContext):
    engine = init_db()
    db_session = get_session(engine)
    try:
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not user:
            await message.answer("Вы не зарегистрированы в системе.")
            return
        # Устанавливаем контекст возврата в меню управления пулами
        await state.update_data(back_to="pools_management")
        modes = db_session.query(Mode).filter(Mode.user_id == user.id).all()
        if not modes:
            await message.answer("У вас пока нет добавленных пулов.")
            await message.answer("Для выхода нажмите Назад.", reply_markup=get_back_keyboard())
            return
        # Первую страницу
        kb = get_delete_modes_keyboard(modes, page=1, page_size=5)
        await message.answer("Выберите пул для удаления:", reply_markup=kb)
        # Отдельно включаем клавиатуру возврата
        await message.answer("Для выхода нажмите Назад.", reply_markup=get_back_keyboard())
    finally:
        db_session.close()


async def process_delete_mode_callback(callback: types.CallbackQuery, state: FSMContext):
    engine = init_db()
    db_session = get_session(engine)
    try:
        data = callback.data  # del_mode_<id>
        mode_id = int(data.split("_")[-1])
        user = db_session.query(User).filter(User.tg_id == callback.from_user.id).first()
        if not user:
            await callback.message.answer("Вы не зарегистрированы в системе.")
            await callback.answer()
            return
        mode = db_session.query(Mode).filter(Mode.id == mode_id, Mode.user_id == user.id).first()
        if not mode:
            await callback.answer("Пул не найден.")
            return
        db_session.delete(mode)
        db_session.commit()
        await callback.answer("Пул удалён.")
        # Перерисуем список с первой страницы
        modes = db_session.query(Mode).filter(Mode.user_id == user.id).all()
        if modes:
            kb = get_delete_modes_keyboard(modes, page=1, page_size=5)
            try:
                await callback.message.edit_reply_markup(reply_markup=kb)
            except Exception:
                await callback.message.answer("Обновлённый список пулов:", reply_markup=kb)
        else:
            # Нет пулов — переходим в меню управления пулами и очищаем back_to
            try:
                await callback.message.edit_text("У вас больше нет пулов.")
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                await callback.message.answer("У вас больше нет пулов.")
            await state.update_data(back_to=None)
            await callback.message.answer("Меню управления пулами:", reply_markup=get_pools_management_keyboard())
    except Exception:
        try:
            await callback.answer("Ошибка удаления пула.")
        except Exception:
            pass
    finally:
        db_session.close()


async def process_delete_modes_pagination(callback: types.CallbackQuery):
    engine = init_db()
    db_session = get_session(engine)
    try:
        data = callback.data  # del_next_<page> / del_prev_<page>
        parts = data.split("_")
        direction = parts[1]
        page = int(parts[2])
        user = db_session.query(User).filter(User.tg_id == callback.from_user.id).first()
        if not user:
            await callback.answer("Нет доступа.")
            return
        modes = db_session.query(Mode).filter(Mode.user_id == user.id).all()
        kb = get_delete_modes_keyboard(modes, page=page, page_size=5)
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            await callback.message.answer("Список пулов:", reply_markup=kb)
        await callback.answer()
    finally:
        db_session.close()


def register_menu_handlers(dp: Dispatcher):
    # Разделы
    dp.message.register(cmd_pool_management, F.text == "Управление пулами")
    dp.message.register(cmd_settings, F.text == "Настройки")
    dp.message.register(cmd_my_devices, F.text == "Мои аппараты")
    dp.message.register(cmd_back, F.text == "Назад")

    # Синонимы для существующих команд под новые кнопки
    dp.message.register(cmd_addmode, F.text == "Добавить пул")

    async def cmd_modes_wrapper(msg: types.Message):
        engine = init_db()
        db_session = get_session(engine)
        try:
            await cmd_modes(msg, db_session)
        finally:
            db_session.close()

    dp.message.register(cmd_modes_wrapper, F.text == "Список пулов")

    # Удаление пулов с пагинацией
    dp.message.register(cmd_delete_mode_start, F.text == "Удалить пул")
    dp.callback_query.register(process_delete_mode_callback, F.data.startswith("del_mode_"))
    dp.callback_query.register(process_delete_modes_pagination, F.data.startswith("del_next_"))
    dp.callback_query.register(process_delete_modes_pagination, F.data.startswith("del_prev_"))


def _format_uptime(delta) -> str:
    try:
        total = int(delta.total_seconds())
    except Exception:
        return "—"
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if not parts:
        parts.append(f"{seconds}с")
    return " ".join(parts)


async def cmd_my_devices(message: types.Message):
    """Показ списка аппаратов пользователя с статусом и аптаймом"""
    engine = init_db()
    db_session = get_session(engine)
    try:
        user = db_session.query(User).filter(User.tg_id == message.from_user.id).first()
        if not user:
            await message.answer("Вы не зарегистрированы в системе.")
            return

        devices = db_session.query(Device).filter(Device.user_id == user.id).all()
        if not devices:
            await message.answer("Пока нет подключённых аппаратов.", reply_markup=get_back_keyboard())
            return

        lines = []
        now = datetime.utcnow()
        for idx, dev in enumerate(devices, start=1):
            name = dev.name or dev.worker or f"Аппарат {idx}"
            status = "онлайн" if (dev.is_online or 0) else "оффлайн"
            # Аптайм: онлайн — с момента подключения до сейчас; оффлайн — с подключения до последнего появления
            if dev.last_connected_at:
                end_time = now if status == "онлайн" else dev.last_seen_at
                if end_time and end_time >= dev.last_connected_at:
                    uptime = _format_uptime(end_time - dev.last_connected_at)
                else:
                    uptime = "—"
            else:
                uptime = "—"

            worker_info = f" ({dev.worker})" if getattr(dev, "worker", None) else ""
            lines.append(f"{idx}. {name}{worker_info} — {status}, аптайм {uptime}")

        text = "Ваши аппараты:\n" + "\n".join(lines)
        await message.answer(text, reply_markup=get_back_keyboard())
    finally:
        db_session.close()