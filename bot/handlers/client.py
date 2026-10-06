"""Сценарий клиента: заполнение и отправка заявки.

Диалог разбит на короткие шаги: заказчику не нужно писать «простыню»
одним сообщением, а бот получает данные в предсказуемом виде.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import db
from bot.config import Config
from bot.keyboards import (
    BTN_ABOUT,
    BTN_CANCEL,
    BTN_MY_APPLICATIONS,
    BTN_NEW_APPLICATION,
    application_card,
    cancel_menu,
    confirm_menu,
    main_menu,
)
from bot.validators import format_phone, normalize_phone, validate_comment, validate_name

logger = logging.getLogger(__name__)

router = Router(name="client")

# Бот работает только в личных чатах. Без этого фильтра он реагировал бы
# на каждое сообщение в группе, куда его добавили.
router.message.filter(F.chat.type == "private")


class ApplicationForm(StatesGroup):
    """Шаги заполнения заявки."""

    name = State()
    phone = State()
    comment = State()
    confirm = State()


def _esc(text: str | None) -> str:
    """Экранирование пользовательского текста — сообщения уходят в HTML-разметке."""
    return html.escape(text or "")


async def _notify_admins(
    bot: Bot, admin_ids: list[int], text: str, reply_markup=None
) -> int:
    """Рассылает уведомление всем админам. Возвращает число доставленных."""
    delivered = 0
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
            delivered += 1
        except TelegramForbiddenError:
            # Админ не начинал диалог с ботом или заблокировал его
            logger.warning(
                "Админ %s недоступен: не нажал /start или заблокировал бота", admin_id
            )
        except TelegramAPIError as error:
            logger.error("Не удалось отправить уведомление админу %s: %s", admin_id, error)
    return delivered


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, config: Config) -> None:
    await state.clear()
    await message.answer(
        f"Здравствуйте! Это бот приёма заявок <b>{_esc(config.company_name)}</b>.\n\n"
        "Оставьте заявку — менеджер свяжется с вами и уточнит детали.\n"
        "Отвечаем в рабочее время, обычно в течение часа.",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, config: Config) -> None:
    await message.answer(
        "Что умеет бот:\n"
        f"• {BTN_NEW_APPLICATION} — заполнить и отправить заявку;\n"
        f"• {BTN_MY_APPLICATIONS} — посмотреть свои заявки и их статусы;\n"
        f"• {BTN_ABOUT} — информация о компании.\n\n"
        "Отменить заполнение можно кнопкой «Отмена» или командой /cancel.",
        reply_markup=main_menu(),
    )


@router.message(Command("id"))
async def show_my_id(message: Message) -> None:
    """Доступно всем: помогает узнать свой ID для настройки ADMIN_IDS."""
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n\n"
        "Если вы администратор — впишите этот номер в ADMIN_IDS в файле .env "
        "и перезапустите бота."
    )


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cancel_form(message: Message, state: FSMContext) -> None:
    """Отмена доступна на любом шаге — регистрируется раньше остальных хендлеров."""
    current = await state.get_state()
    await state.clear()

    if current is None:
        await message.answer("Сейчас нечего отменять.", reply_markup=main_menu())
        return

    await message.answer("Заполнение отменено.", reply_markup=main_menu())


@router.message(F.text == BTN_ABOUT, StateFilter(None))
async def show_about(message: Message, config: Config) -> None:
    text = (
        f"<b>{_esc(config.company_name)}</b>\n\n"
        f"{_esc(config.company_description)}"
    )
    if config.manager_contact:
        text += f"\n\nСвязаться напрямую: {_esc(config.manager_contact)}"

    await message.answer(text, reply_markup=main_menu())


@router.message(F.text == BTN_MY_APPLICATIONS, StateFilter(None))
async def show_my_applications(message: Message) -> None:
    applications = await db.list_user_applications(message.from_user.id, limit=5)

    if not applications:
        await message.answer(
            "У вас пока нет заявок. Нажмите «Оставить заявку» — это займёт минуту.",
            reply_markup=main_menu(),
        )
        return

    lines = ["<b>Ваши последние заявки:</b>", ""]
    for app in applications:
        lines.append(
            f"№{app.id} · {app.created_at_local.strftime('%d.%m.%Y %H:%M')} — "
            f"{app.status_emoji} <b>{_esc(app.status_label)}</b>"
        )
    lines.append("")
    lines.append("Менеджер свяжется с вами по указанному номеру.")

    await message.answer("\n".join(lines), reply_markup=main_menu())


# --- Пошаговое заполнение заявки ---


@router.message(F.text == BTN_NEW_APPLICATION, StateFilter(None))
async def start_form(message: Message, state: FSMContext) -> None:
    await state.set_state(ApplicationForm.name)
    await message.answer(
        "Как к вам обращаться? Напишите имя.",
        reply_markup=cancel_menu(),
    )


@router.message(ApplicationForm.name)
async def process_name(message: Message, state: FSMContext) -> None:
    error = validate_name(message.text)
    if error:
        await message.answer(error, reply_markup=cancel_menu())
        return

    await state.update_data(name=message.text.strip())
    await state.set_state(ApplicationForm.phone)
    await message.answer(
        "Отлично. Теперь номер телефона для связи.\n"
        "Можно в любом формате: +7 999 123-45-67, 8 999 123 45 67.",
        reply_markup=cancel_menu(),
    )


@router.message(ApplicationForm.phone)
async def process_phone(message: Message, state: FSMContext) -> None:
    phone = normalize_phone(message.text)
    if phone is None:
        await message.answer(
            "Не похоже на номер телефона. Пример: +7 999 123-45-67.",
            reply_markup=cancel_menu(),
        )
        return

    await state.update_data(phone=phone)
    await state.set_state(ApplicationForm.comment)
    await message.answer(
        "Что нужно сделать? Опишите задачу в двух-трёх предложениях.\n\n"
        "Если сказать пока нечего — отправьте «-».",
        reply_markup=cancel_menu(),
    )


@router.message(ApplicationForm.comment)
async def process_comment(message: Message, state: FSMContext) -> None:
    error = validate_comment(message.text)
    if error:
        await message.answer(error, reply_markup=cancel_menu())
        return

    comment = (message.text or "").strip()
    if comment == "-":
        comment = ""

    await state.update_data(comment=comment)
    await state.set_state(ApplicationForm.confirm)

    data = await state.get_data()
    summary = (
        "<b>Проверьте заявку:</b>\n\n"
        f"👤 Имя: {_esc(data.get('name'))}\n"
        f"📞 Телефон: {_esc(format_phone(data.get('phone', '')))}\n"
        f"💬 Задача: {_esc(comment) if comment else '—'}"
    )

    await message.answer(summary, reply_markup=confirm_menu())


@router.callback_query(F.data == "app:confirm", ApplicationForm.confirm)
async def confirm_application(
    callback: CallbackQuery, state: FSMContext, bot: Bot, config: Config
) -> None:
    """Сохраняет заявку и уведомляет админов."""
    data = await state.get_data()
    await state.clear()

    await callback.answer("Отправляем…")

    if not data.get("name") or not data.get("phone"):
        # Состояние потерялось (например, бот перезапускался) — просим заполнить заново
        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                "Данные заявки потерялись. Заполните её заново, пожалуйста."
            )
        return

    app_id = await db.create_application(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=data["name"],
        phone=data["phone"],
        comment=data.get("comment") or None,
    )

    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            f"✅ Заявка №{app_id} принята!\n\n"
            "Менеджер свяжется с вами по указанному номеру. "
            "Статус заявки можно посмотреть в разделе «Мои заявки»."
        )

    application = await db.get_application(app_id)
    if application is None:
        logger.error("Заявка №%s не найдена сразу после создания", app_id)
        return

    text = (
        f"🆕 <b>Новая заявка №{application.id}</b>\n\n"
        f"👤 Имя: {_esc(application.full_name)}\n"
        f"📞 Телефон: {_esc(format_phone(application.phone))}\n"
        f"💬 Задача: {_esc(application.comment) if application.comment else '—'}\n"
        f"🔗 Клиент: {_esc(application.client_link)}\n"
        f"🕐 {application.created_at_local.strftime('%d.%m.%Y %H:%M')}"
    )

    delivered = await _notify_admins(
        bot, config.admin_ids, text, application_card(application.id)
    )
    if not delivered:
        logger.error(
            "Заявка №%s сохранена, но ни одному админу не доставлена. "
            "Проверьте ADMIN_IDS и что админы нажали /start.",
            app_id,
        )


@router.callback_query(F.data == "app:restart", ApplicationForm.confirm)
async def restart_form(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ApplicationForm.name)
    await state.update_data(name=None, phone=None, comment=None)

    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Хорошо, начнём заново.")
        await callback.message.answer(
            "Как к вам обращаться? Напишите имя.", reply_markup=cancel_menu()
        )


# --- Запасные хендлеры ---
# Регистрируются последними, поэтому срабатывают только если ничего
# выше не подошло.


@router.callback_query(F.data.startswith("app:"))
async def stale_callback(callback: CallbackQuery) -> None:
    """Кнопки старой заявки: состояние потерялось, например после перезапуска."""
    await callback.answer("Кнопка устарела", show_alert=True)
    if isinstance(callback.message, Message):
        await callback.message.edit_text(
            "Эта заявка уже неактуальна — начните новую, пожалуйста.",
            reply_markup=main_menu(),
        )


@router.message(StateFilter(None))
async def fallback(message: Message) -> None:
    """Ответ на всё, что не подошло под другие хендлеры.

    Молчание бота заказчик воспринимает как поломку, поэтому лучше
    подсказать, что делать дальше.
    """
    await message.answer(
        "Не понял сообщение. Воспользуйтесь кнопками ниже — "
        "или нажмите «Оставить заявку», если хотите задать вопрос.",
        reply_markup=main_menu(),
    )
