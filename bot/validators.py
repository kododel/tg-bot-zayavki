"""Проверка и нормализация ввода.

Клиенты в Telegram пишут телефон как угодно: `8 999 123-45-67`,
`+7(999)1234567`, `9991234567`. Задача — привести это к одному виду
и не пропустить явный мусор.
"""

from __future__ import annotations

import re

# Имя: буквы (русские и латиница), пробел, дефис, точка, апостроф
_NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\s\-\.']*$")
_PHONE_ALLOWED_RE = re.compile(r"^[\d\s\+\-\(\)]+$")

MIN_NAME_LEN = 2
MAX_NAME_LEN = 60
MIN_PHONE_DIGITS = 10
MAX_PHONE_DIGITS = 15
MAX_COMMENT_LEN = 500

NAME_ERROR = (
    "Похоже, в имени опечатка. Напишите его буквами, например: «Иван Петров»."
)
PHONE_ERROR = (
    "Не похоже на номер телефона. Пример: +7 999 123-45-67 "
    "или 89991234567."
)


def validate_name(raw: str | None) -> str | None:
    """Текст ошибки или None, если имя корректно."""
    value = (raw or "").strip()

    if len(value) < MIN_NAME_LEN:
        return "Имя слишком короткое — напишите, как к вам обращаться."
    if len(value) > MAX_NAME_LEN:
        return f"Имя длиннее {MAX_NAME_LEN} символов. Сократите, пожалуйста."
    if not _NAME_RE.match(value):
        return NAME_ERROR
    if not any(ch.isalpha() for ch in value):
        return NAME_ERROR
    return None


def normalize_phone(raw: str | None) -> str | None:
    """Приводит номер к виду `+79991234567`. None — если номер невалиден."""
    value = (raw or "").strip()
    if not value or not _PHONE_ALLOWED_RE.match(value):
        return None

    digits = re.sub(r"\D", "", value)

    # 8 999 123 45 67 -> 7 999 123 45 67
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    # 999 123 45 67 -> 7 999 123 45 67
    elif len(digits) == 10:
        digits = "7" + digits

    if not (MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS):
        return None

    return f"+{digits}"


def format_phone(phone: str) -> str:
    """+79991234567 -> +7 999 123-45-67 (для красивого показа)."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11:
        return f"+{digits[0]} {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return phone


def validate_comment(raw: str | None) -> str | None:
    """Текст ошибки или None. Пустой комментарий допустим."""
    value = (raw or "").strip()
    if len(value) > MAX_COMMENT_LEN:
        return (
            f"Комментарий длиннее {MAX_COMMENT_LEN} символов. "
            "Сократите, пожалуйста, — остальное можно уточнить в переписке."
        )
    return None
