"""Настройки бота.

Все секреты и параметры читаются из переменных окружения (файл .env).
Так проект можно передать заказчику и запустить где угодно,
не переписывая код.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Читаем .env из корня проекта
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _parse_admin_ids(raw: str) -> list[int]:
    """Превращает строку '123,456' в список [123, 456].

    Молча пропускает мусор — лучше запуститься с частью админов,
    чем упасть на старте из-за лишней запятой.
    """
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.append(int(chunk))
    return ids


@dataclass(frozen=True)
class Config:
    """Конфигурация приложения."""

    bot_token: str
    admin_ids: list[int] = field(default_factory=list)

    company_name: str = "Наша компания"
    company_description: str = "Опишите здесь, чем занимается компания."
    manager_contact: str = ""

    # Страна для проверки телефона: "RU" — по правилам российской нумерации,
    # "ANY" — только общие проверки, если клиенты бывают из других стран.
    phone_country: str = "RU"

    db_path: Path = BASE_DIR / "data" / "applications.db"
    export_dir: Path = BASE_DIR / "data" / "exports"

    @property
    def is_valid(self) -> bool:
        """Готов ли конфиг к запуску."""
        return bool(self.bot_token)

    def problems(self) -> list[str]:
        """Список проблем конфигурации — показываем их при старте."""
        issues: list[str] = []
        if not self.bot_token:
            issues.append("Не задан BOT_TOKEN — возьмите его у @BotFather.")
        if not self.admin_ids:
            issues.append(
                "Не задан ADMIN_IDS — бот запустится, но заявки будет некому отправлять."
            )
        return issues


def load_config() -> Config:
    """Собирает конфиг из окружения."""
    return Config(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        company_name=os.getenv("COMPANY_NAME", "Наша компания").strip(),
        company_description=os.getenv(
            "COMPANY_DESCRIPTION", "Опишите здесь, чем занимается компания."
        ).strip(),
        manager_contact=os.getenv("MANAGER_CONTACT", "").strip(),
        phone_country=os.getenv("PHONE_COUNTRY", "RU").strip() or "RU",
        db_path=Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "applications.db"))),
        export_dir=Path(os.getenv("EXPORT_DIR", str(BASE_DIR / "data" / "exports"))),
    )
