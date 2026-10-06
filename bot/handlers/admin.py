"""Админ-панель: список заявок, смена статусов, статистика, выгрузка в Excel.

Доступ закрыт фильтром IsAdmin: id админов берутся из ADMIN_IDS в .env.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot import db
from bot.config import Config
from bot.export import export_applications
from bot.keyboards import (
    PAGE_SIZE,
    admin_menu,
    application_card,
    applications_list,
    back_to_admin_menu,
)
from bot.validators import format_phone

logger = logging.getLogger(__name__)

router = Router(name="admin")

STATUS_TITLES = {
    "all": "Все заявки",
    "new": "Новые заявки",
    "in_progress": "Заявки в работе",
    "done": "Выполненные заявки",
    "rejected": "Отклонённые заявки",
}


def _esc(text: str | None) -> str:
    return html.escape(text or "")


class IsAdmin(BaseFilter):
    """Пускает дальше только id из ADMIN_IDS."""

    async def __call__(self, event: Message | CallbackQuery, config: Config) -> bool:
        user = event.from_user
        return user is not None and user.id in config.admin_ids


# Фильтр на весь роутер: ни один хендлер ниже не сработает для посторонних
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    stats = await db.get_stats()
    await message.answer(
        f"<b>Панель администратора</b>\n\n"
        f"Всего заявок: {stats['total']}\n"
        f"🆕 Новых: {stats['new']} · 🔧 В работе: {stats['in_progress']}",
        reply_markup=admin_menu(),
    )


@router.callback_query(F.data == "admin:noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "admin:menu")
async def show_menu(callback: CallbackQuery) -> None:
    stats = await db.get_stats()
    text = (
        f"<b>Панель администратора</b>\n\n"
        f"Всего заявок: {stats['total']}\n"
        f"🆕 Новых: {stats['new']} · 🔧 В работе: {stats['in_progress']}"
    )

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=admin_menu())


@router.callback_query(F.data == "admin:stats")
async def show_stats(callback: CallbackQuery) -> None:
    stats = await db.get_stats()
    text = (
        "<b>📊 Статистика по заявкам</b>\n\n"
        f"Всего: <b>{stats['total']}</b>\n"
        f"🆕 Новые: {stats['new']}\n"
        f"🔧 В работе: {stats['in_progress']}\n"
        f"✅ Выполнены: {stats['done']}\n"
        f"🚫 Отклонены: {stats['rejected']}\n\n"
        f"За сегодня: {stats['today']}\n"
        f"За 7 дней: {stats['week']}"
    )

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(text, reply_markup=back_to_admin_menu())


@router.callback_query(F.data.startswith("admin:list:"))
async def show_list(callback: CallbackQuery) -> None:
    _, _, status, page_raw = (callback.data or "").split(":")
    page = int(page_raw)

    filter_status = None if status == "all" else status
    total = await db.count_applications(filter_status)
    applications = await db.list_applications(
        status=filter_status, limit=PAGE_SIZE, offset=page * PAGE_SIZE
    )

    title = STATUS_TITLES.get(status, "Заявки")
    if not applications:
        text = f"<b>{title}</b>\n\nПока пусто."
    else:
        text = f"<b>{title}</b> — всего {total}\n\nВыберите заявку, чтобы открыть карточку."

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            text,
            reply_markup=applications_list(
                applications, status=status, page=page, total=total
            ),
        )


async def _render_application_card(callback: CallbackQuery, app_id: int) -> None:
    """Перерисовывает карточку заявки.

    Ответ на callback здесь не отправляется — это делают вызывающие хендлеры,
    иначе Telegram отклонит повторный answerCallbackQuery.
    """
    if not isinstance(callback.message, Message):
        return

    application = await db.get_application(app_id)
    if application is None:
        await callback.message.edit_text(
            f"Заявка №{app_id} не найдена.", reply_markup=back_to_admin_menu()
        )
        return

    text = (
        f"{application.status_emoji} <b>Заявка №{application.id}</b>\n"
        f"Статус: <b>{_esc(application.status_label)}</b>\n\n"
        f"👤 Имя: {_esc(application.full_name)}\n"
        f"📞 Телефон: <code>{_esc(format_phone(application.phone))}</code>\n"
        f"💬 Задача: {_esc(application.comment) if application.comment else '—'}\n"
        f"🔗 Клиент: {_esc(application.client_link)}\n\n"
        f"Создана: {application.created_at_local.strftime('%d.%m.%Y %H:%M')}\n"
        f"Обновлена: {application.updated_at_local.strftime('%d.%m.%Y %H:%M')}"
    )

    await callback.message.edit_text(text, reply_markup=application_card(application.id))


@router.callback_query(F.data.startswith("admin:view:"))
async def show_application(callback: CallbackQuery) -> None:
    app_id = int((callback.data or "").split(":")[2])
    await callback.answer()
    await _render_application_card(callback, app_id)


@router.callback_query(F.data.startswith("admin:set:"))
async def change_status(callback: CallbackQuery) -> None:
    _, _, app_id_raw, status = (callback.data or "").split(":")
    app_id = int(app_id_raw)

    if status not in db.STATUS_LABELS:
        await callback.answer("Неизвестный статус", show_alert=True)
        return

    updated = await db.update_status(app_id, status)
    if not updated:
        await callback.answer(f"Заявка №{app_id} не найдена", show_alert=True)
        return

    await callback.answer(f"Статус: {db.STATUS_LABELS[status]}")
    await _render_application_card(callback, app_id)


@router.callback_query(F.data == "admin:export")
async def export_to_excel(callback: CallbackQuery, bot: Bot, config: Config) -> None:
    await callback.answer("Собираю файл…")
    if not isinstance(callback.message, Message):
        return

    try:
        path = await export_applications(config.export_dir)
    except Exception:  # noqa: BLE001 — показываем админу понятную ошибку
        logger.exception("Не удалось собрать выгрузку в Excel")
        await callback.message.answer(
            "Не получилось собрать файл. Подробности — в логах бота.",
            reply_markup=back_to_admin_menu(),
        )
        return

    applications = await db.count_applications()
    await bot.send_document(
        chat_id=callback.from_user.id,
        document=FSInputFile(path, filename=path.name),
        caption=f"📎 Выгрузка заявок: {applications} шт.\nФайл: {path.name}",
    )
