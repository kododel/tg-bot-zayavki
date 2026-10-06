"""Клавиатуры бота.

Вся разметка кнопок собрана в одном месте: когда заказчик просит
поменять текст или добавить раздел, правка занимает минуту.
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.db import STATUS_EMOJI, STATUS_LABELS

# --- Тексты кнопок главного меню (используются и в фильтрах хендлеров) ---

BTN_NEW_APPLICATION = "📝 Оставить заявку"
BTN_MY_APPLICATIONS = "📋 Мои заявки"
BTN_ABOUT = "ℹ️ О компании"
BTN_CANCEL = "❌ Отмена"

PAGE_SIZE = 5


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню клиента."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NEW_APPLICATION)],
            [KeyboardButton(text=BTN_MY_APPLICATIONS), KeyboardButton(text=BTN_ABOUT)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    """Клавиатура на время заполнения заявки."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
        input_field_placeholder="Введите ответ",
    )


def confirm_menu() -> InlineKeyboardMarkup:
    """Подтверждение перед отправкой заявки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отправить", callback_data="app:confirm")],
            [InlineKeyboardButton(text="✏️ Заполнить заново", callback_data="app:restart")],
        ]
    )


def admin_menu() -> InlineKeyboardMarkup:
    """Главное меню администратора."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
            [
                InlineKeyboardButton(text="🆕 Новые", callback_data="admin:list:new:0"),
                InlineKeyboardButton(
                    text="🔧 В работе", callback_data="admin:list:in_progress:0"
                ),
            ],
            [InlineKeyboardButton(text="🗂 Все заявки", callback_data="admin:list:all:0")],
            [InlineKeyboardButton(text="📎 Выгрузить в Excel", callback_data="admin:export")],
        ]
    )


def back_to_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="admin:menu")]
        ]
    )


def applications_list(
    applications: list,
    *,
    status: str,
    page: int,
    total: int,
) -> InlineKeyboardMarkup:
    """Список заявок + пагинация.

    Каждая заявка — кнопка «#12 · Иванов · 🆕», по нажатию открывается карточка.
    """
    rows: list[list[InlineKeyboardButton]] = []

    for app in applications:
        label = f"#{app.id} · {app.full_name[:20]} · {app.status_emoji}"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"admin:view:{app.id}")]
        )

    # Пагинация
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(text="⬅️", callback_data=f"admin:list:{status}:{page - 1}")
        )
    if total_pages > 1:
        nav.append(
            InlineKeyboardButton(
                text=f"{page + 1} / {total_pages}", callback_data="admin:noop"
            )
        )
    if page + 1 < total_pages:
        nav.append(
            InlineKeyboardButton(text="➡️", callback_data=f"admin:list:{status}:{page + 1}")
        )
    if nav:
        rows.append(nav)

    rows.append(
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="admin:menu")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def application_card(app_id: int) -> InlineKeyboardMarkup:
    """Кнопки смены статуса для карточки заявки."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    for status, label in STATUS_LABELS.items():
        row.append(
            InlineKeyboardButton(
                text=f"{STATUS_EMOJI[status]} {label}",
                callback_data=f"admin:set:{app_id}:{status}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="admin:list:all:0")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
