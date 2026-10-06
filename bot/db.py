"""Слой работы с базой данных.

Одна таблица заявок + набор функций. SQLite выбран не от лени:
для потока заявок от одного-двух десятков менеджеров этого хватает
с большим запасом, а заказчику не нужно ничего поднимать и обслуживать.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import aiosqlite


class Status(str, Enum):
    """Статусы заявки."""

    NEW = "new"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    REJECTED = "rejected"


STATUS_LABELS: dict[str, str] = {
    Status.NEW.value: "Новая",
    Status.IN_PROGRESS.value: "В работе",
    Status.DONE.value: "Выполнена",
    Status.REJECTED.value: "Отклонена",
}

STATUS_EMOJI: dict[str, str] = {
    Status.NEW.value: "🆕",
    Status.IN_PROGRESS.value: "🔧",
    Status.DONE.value: "✅",
    Status.REJECTED.value: "🚫",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    username    TEXT,
    full_name   TEXT    NOT NULL,
    phone       TEXT    NOT NULL,
    comment     TEXT,
    status      TEXT    NOT NULL DEFAULT 'new',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_applications_status     ON applications (status);
CREATE INDEX IF NOT EXISTS idx_applications_user       ON applications (user_id);
CREATE INDEX IF NOT EXISTS idx_applications_created_at ON applications (created_at);
"""


@dataclass(frozen=True)
class Application:
    """Заявка в удобном для кода виде."""

    id: int
    user_id: int
    username: str | None
    full_name: str
    phone: str
    comment: str | None
    status: str
    created_at: str
    updated_at: str

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def status_emoji(self) -> str:
        return STATUS_EMOJI.get(self.status, "•")

    @property
    def created_at_local(self) -> datetime:
        """Время создания в часовом поясе сервера — для показа пользователю."""
        return _to_local(self.created_at)

    @property
    def updated_at_local(self) -> datetime:
        return _to_local(self.updated_at)

    @property
    def client_link(self) -> str:
        """Ссылка на диалог с клиентом, если у него есть username."""
        return f"@{self.username}" if self.username else f"id{self.user_id}"


# Единственное соединение на процесс. Открывается в init_db().
_conn: aiosqlite.Connection | None = None


def _to_local(iso: str) -> datetime:
    """ISO-строка (UTC) -> локальное время для отображения."""
    try:
        return datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return datetime.now()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn_or_raise() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("База не инициализирована: вызовите init_db() при старте.")
    return _conn


def _row_to_application(row: aiosqlite.Row) -> Application:
    return Application(
        id=row["id"],
        user_id=row["user_id"],
        username=row["username"],
        full_name=row["full_name"],
        phone=row["phone"],
        comment=row["comment"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def init_db(db_path: Path) -> None:
    """Открывает соединение и создаёт схему, если её ещё нет."""
    global _conn

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _conn = await aiosqlite.connect(db_path)
    _conn.row_factory = aiosqlite.Row
    # WAL заметно лучше держит одновременную запись и чтение
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA foreign_keys=ON")
    await _conn.executescript(SCHEMA)
    await _conn.commit()


async def close_db() -> None:
    """Закрывает соединение при остановке бота."""
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


async def create_application(
    *,
    user_id: int,
    username: str | None,
    full_name: str,
    phone: str,
    comment: str | None,
) -> int:
    """Создаёт заявку и возвращает её номер."""
    conn = _conn_or_raise()
    now = _now()
    cursor = await conn.execute(
        """
        INSERT INTO applications
            (user_id, username, full_name, phone, comment, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            full_name,
            phone,
            comment,
            Status.NEW.value,
            now,
            now,
        ),
    )
    await conn.commit()
    return int(cursor.lastrowid or 0)


async def get_application(app_id: int) -> Application | None:
    """Заявка по номеру или None, если такой нет."""
    conn = _conn_or_raise()
    async with conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)) as cursor:
        row = await cursor.fetchone()
    return _row_to_application(row) if row else None


async def list_applications(
    *,
    status: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[Application]:
    """Список заявок: свежие сверху, с фильтром по статусу и постранично."""
    conn = _conn_or_raise()

    if status is None:
        query = "SELECT * FROM applications ORDER BY id DESC LIMIT ? OFFSET ?"
        params: tuple[Any, ...] = (limit, offset)
    else:
        query = (
            "SELECT * FROM applications WHERE status = ? "
            "ORDER BY id DESC LIMIT ? OFFSET ?"
        )
        params = (status, limit, offset)

    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()
    return [_row_to_application(row) for row in rows]


async def list_user_applications(user_id: int, limit: int = 5) -> list[Application]:
    """Последние заявки конкретного клиента — для раздела «Мои заявки»."""
    conn = _conn_or_raise()
    async with conn.execute(
        "SELECT * FROM applications WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [_row_to_application(row) for row in rows]


async def count_applications(status: str | None = None) -> int:
    """Сколько всего заявок (или сколько с указанным статусом)."""
    conn = _conn_or_raise()

    if status is None:
        query, params = "SELECT COUNT(*) FROM applications", ()
    else:
        query, params = "SELECT COUNT(*) FROM applications WHERE status = ?", (status,)

    async with conn.execute(query, params) as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def update_status(app_id: int, status: str) -> bool:
    """Меняет статус заявки. False — если заявка не найдена."""
    conn = _conn_or_raise()
    cursor = await conn.execute(
        "UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), app_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def _count_since(moment: datetime) -> int:
    conn = _conn_or_raise()
    async with conn.execute(
        "SELECT COUNT(*) FROM applications WHERE created_at >= ?",
        (moment.astimezone(timezone.utc).isoformat(timespec="seconds"),),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def get_stats() -> dict[str, Any]:
    """Сводка для админ-панели."""
    conn = _conn_or_raise()

    async with conn.execute(
        "SELECT status, COUNT(*) FROM applications GROUP BY status"
    ) as cursor:
        rows = await cursor.fetchall()

    by_status = {row[0]: int(row[1]) for row in rows}
    total = sum(by_status.values())

    now_local = datetime.now().astimezone()
    start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    return {
        "total": total,
        "by_status": by_status,
        "new": by_status.get(Status.NEW.value, 0),
        "in_progress": by_status.get(Status.IN_PROGRESS.value, 0),
        "done": by_status.get(Status.DONE.value, 0),
        "rejected": by_status.get(Status.REJECTED.value, 0),
        "today": await _count_since(start_of_today),
        "week": await _count_since(start_of_today - timedelta(days=6)),
    }


async def all_for_export() -> list[Application]:
    """Все заявки по возрастанию номера — для выгрузки в Excel."""
    conn = _conn_or_raise()
    async with conn.execute("SELECT * FROM applications ORDER BY id ASC") as cursor:
        rows = await cursor.fetchall()
    return [_row_to_application(row) for row in rows]
