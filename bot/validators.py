"""Проверка и нормализация ввода.

Телефон — самое больное место любой формы. Клиенты пишут `8 999 123-45-67`,
`+7(999)1234567`, `9991234567`, а иногда просто тыкают пальцем в клавиатуру.

Важно понимать предел: без подтверждения по SMS доказать, что номер
существует и принадлежит этому человеку, нельзя. Можно только отбросить
заведомо невозможные. Поэтому проверка жёсткая по смыслу, но с лазейкой:
если заказчик обслуживает иностранных клиентов, `PHONE_COUNTRY=ANY`
отключает правила нумерации и оставляет только общие проверки.
"""

from __future__ import annotations

import re

# Имя: буквы (русские и латиница), пробел, дефис, точка, апостроф
_NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z][А-Яа-яЁёA-Za-z\s\-\.']*$")
_PHONE_ALLOWED_RE = re.compile(r"^[\d\s\+\-\(\)]+$")

MIN_NAME_LEN = 2
MAX_NAME_LEN = 60
MAX_COMMENT_LEN = 500

# Российский номер: 11 цифр, первая — код страны 7, дальше 10 цифр.
RU_COUNTRY_CODE = "7"
RU_TOTAL_DIGITS = 11

# Первая цифра национального номера. В России выданы диапазоны,
# начинающиеся на 3, 4, 8 и 9 (мобильные — на 9). Кодов на 1, 2, 5, 6, 7
# не существует, поэтому такие номера почти наверняка выдуманы.
RU_VALID_FIRST_DIGITS = frozenset("3489")

# Общие рамки для любой страны: короче 10 цифр — не номер,
# длиннее 15 — уже не влезает в стандарт E.164.
MIN_PHONE_DIGITS = 10
MAX_PHONE_DIGITS = 15

NAME_ERROR = (
    "Похоже, в имени опечатка. Напишите его буквами, например: «Иван Петров»."
)
PHONE_FORMAT_ERROR = (
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


def _looks_random(digits: str) -> bool:
    """Отсеивает номера, набранные «лишь бы что-нибудь».

    Ловит три типовых случая: все цифры одинаковые (7777777777),
    ровная последовательность (1234567890) и повторяющийся блок
    (1212121212). Настоящий номер так выглядит крайне редко.
    """
    if len(set(digits)) == 1:
        return True

    ascending = "0123456789" * 2
    descending = "9876543210" * 2
    if digits in ascending or digits in descending:
        return True

    for size in (2, 3, 4, 5):
        if len(digits) % size:
            continue
        blocks = {digits[i : i + size] for i in range(0, len(digits), size)}
        if len(blocks) == 1:
            return True

    return False


def check_phone(
    raw: str | None, *, country: str = "RU"
) -> tuple[str | None, str | None]:
    """Проверяет телефон и приводит его к виду `+79991234567`.

    Возвращает пару (номер, ошибка): заполнено ровно одно из двух.
    """
    value = (raw or "").strip()

    if not value:
        return None, "Номер не указан. Напишите его, пожалуйста."
    if not _PHONE_ALLOWED_RE.match(value):
        return None, PHONE_FORMAT_ERROR

    digits = re.sub(r"\D", "", value)
    if not digits:
        return None, PHONE_FORMAT_ERROR

    # 8 999 123 45 67 -> 7 999 123 45 67 (привычная россиянам запись)
    if len(digits) == RU_TOTAL_DIGITS and digits.startswith("8"):
        digits = RU_COUNTRY_CODE + digits[1:]
    # 999 123 45 67 -> 7 999 123 45 67 (номер без кода страны)
    elif len(digits) == 10 and country.upper() == "RU":
        digits = RU_COUNTRY_CODE + digits

    if not (MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS):
        return None, (
            f"В номере {len(digits)} цифр — для телефона это не подходит. "
            "Пример: +7 999 123-45-67."
        )

    random_hint = "Похоже, номер набран случайно. Проверьте цифры, пожалуйста."

    if country.upper() == "RU" and digits.startswith(RU_COUNTRY_CODE):
        # Значимая часть номера — без кода страны. «Случайность» проверяем
        # именно её: с приклеенной семёркой шаблоны вида 9876543210
        # перестают опознаваться, и последовательность проходит как номер.
        national = digits[len(RU_COUNTRY_CODE) :]

        if len(national) != RU_TOTAL_DIGITS - 1:
            return None, (
                "В российском номере должно быть 11 цифр, включая +7. "
                "Пример: +7 999 123-45-67."
            )
        if _looks_random(national):
            return None, random_hint
        if national[0] not in RU_VALID_FIRST_DIGITS:
            return None, (
                "Такого кода в России не существует. Проверьте номер — "
                "или напишите его в формате +7 999 123-45-67."
            )
    elif _looks_random(digits):
        return None, random_hint

    return f"+{digits}", None


def normalize_phone(raw: str | None, *, country: str = "RU") -> str | None:
    """Короткая обёртка: только номер, без текста ошибки."""
    return check_phone(raw, country=country)[0]


def format_phone(phone: str) -> str:
    """+79991234567 -> +7 999 123-45-67 (для красивого показа)."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == RU_TOTAL_DIGITS and digits.startswith(RU_COUNTRY_CODE):
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
