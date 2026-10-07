"""Смоук-тест: проверяет, что бот собирается и базовые сценарии работают.

Запуск из корня проекта:
    python scripts/smoke_test.py

Тест не требует токена Telegram и не ходит в сеть — проверяются
валидаторы, слой БД, выгрузка в Excel и сборка клавиатур.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

# Чтобы скрипт запускался и как `python scripts/smoke_test.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import load_workbook  # noqa: E402

from bot import db, validators  # noqa: E402
from bot.export import export_applications  # noqa: E402
from bot.keyboards import (  # noqa: E402
    admin_menu,
    application_card,
    applications_list,
    confirm_menu,
    main_menu,
)

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))
        FAILURES.append(name)


def test_validators() -> None:
    print("\n[1/5] Валидаторы")

    phones = {
        "+7 999 123-45-67": "+79991234567",
        "8 999 123 45 67": "+79991234567",
        "9991234567": "+79991234567",
        "+79991234567": "+79991234567",
        "(999) 123-45-67": "+79991234567",
    }
    for raw, expected in phones.items():
        actual = validators.normalize_phone(raw)
        check(f"телефон {raw!r} -> {expected}", actual == expected, f"получено {actual!r}")

    for bad in ["", "позвоните мне", "123", "+7 999 123 45 67 89 10 11", "телефон: 8-999"]:
        check(
            f"мусор {bad!r} отклонён",
            validators.normalize_phone(bad) is None,
            f"получено {validators.normalize_phone(bad)!r}",
        )

    # --- Проверка правдоподобия номера: раньше пропускалось всё, где
    # --- 10–15 цифр подряд. Именно на этом мы и погорели.
    check(
        "случайные цифры 6593751033 отклонены",
        validators.normalize_phone("6593751033") is None,
        f"получено {validators.normalize_phone('6593751033')!r}",
    )
    check(
        "несуществующий код +7 659 отклонён",
        validators.normalize_phone("+7 659 375-10-33") is None,
    )
    check(
        "код на 1 отклонён",
        validators.normalize_phone("1234567890") is None,
    )
    check("все цифры одинаковые отклонены", validators.normalize_phone("7777777777") is None)
    check("повторяющийся блок отклонён", validators.normalize_phone("1212121212") is None)
    check(
        "убывающая последовательность 9876543210 отклонена",
        validators.normalize_phone("9876543210") is None,
        f"получено {validators.normalize_phone('9876543210')!r}",
    )

    # Реальные номера, которые обязаны проходить
    for good, expected in {
        "9991234567": "+79991234567",      # мобильный без кода страны
        "8 999 123 45 67": "+79991234567",  # привычная запись через 8
        "+7 999 123-45-67": "+79991234567",
        "4951234567": "+74951234567",       # московский городской
        "8121234567": "+78121234567",       # петербургский городской
    }.items():
        actual = validators.normalize_phone(good)
        check(f"реальный номер {good!r} принят", actual == expected, f"получено {actual!r}")

    # Зарубежный номер: при PHONE_COUNTRY=ANY правила нумерации не применяются
    check(
        "зарубежный номер при country=ANY принят",
        validators.normalize_phone("+375291234567", country="ANY") == "+375291234567",
        f"получено {validators.normalize_phone('+375291234567', country='ANY')!r}",
    )
    check(
        "тот же номер при country=RU проходит только по общим правилам",
        validators.normalize_phone("+375291234567") == "+375291234567",
    )

    # Проверяем, что у ошибок есть внятный текст, а не просто None
    _, error = validators.check_phone("6593751033")
    check("ошибка объясняет причину", bool(error) and "код" in error.lower(), str(error))
    _, error = validators.check_phone("")
    check("пустой номер даёт понятную ошибку", bool(error), str(error))

    check("имя «Иван Петров» принято", validators.validate_name("Иван Петров") is None)
    check("имя «Анна-Мария» принято", validators.validate_name("Анна-Мария") is None)
    check("имя «X» отклонено", validators.validate_name("X") is not None)
    check("имя «12345» отклонено", validators.validate_name("12345") is not None)
    check("пустое имя отклонено", validators.validate_name("") is not None)
    check("длинный комментарий отклонён", validators.validate_comment("я" * 501) is not None)
    check("пустой комментарий принят", validators.validate_comment("") is None)

    check(
        "форматирование телефона",
        validators.format_phone("+79991234567") == "+7 999 123-45-67",
        validators.format_phone("+79991234567"),
    )


async def test_database(tmp: Path) -> None:
    print("\n[2/5] База данных")
    await db.init_db(tmp / "test.db")

    first_id = await db.create_application(
        user_id=111,
        username="ivan",
        full_name="Иван Петров",
        phone="+79991234567",
        comment="Нужен бот для заявок",
    )
    second_id = await db.create_application(
        user_id=222,
        username=None,
        full_name="Мария",
        phone="+79990001122",
        comment=None,
    )

    check("заявки получили номера", first_id == 1 and second_id == 2, f"{first_id}, {second_id}")

    application = await db.get_application(first_id)
    check("заявка читается по id", application is not None and application.full_name == "Иван Петров")
    check("статус новой заявки — new", application is not None and application.status == db.Status.NEW.value)
    check("метка статуса на русском", application is not None and application.status_label == "Новая")
    check("ссылка на клиента по username", application is not None and application.client_link == "@ivan")

    check("всего заявок 2", await db.count_applications() == 2)
    check("новых заявок 2", await db.count_applications("new") == 2)

    updated = await db.update_status(first_id, db.Status.IN_PROGRESS.value)
    check("статус обновлён", updated is True)
    check("в работе 1 заявка", await db.count_applications("in_progress") == 1)
    check("несуществующая заявка не обновляется", await db.update_status(9999, "done") is False)

    mine = await db.list_user_applications(111)
    check("свои заявки находятся", len(mine) == 1 and mine[0].id == first_id)
    check("чужие заявки не попадают", all(a.user_id == 111 for a in mine))

    stats = await db.get_stats()
    check("статистика: всего 2", stats["total"] == 2)
    check("статистика: за сегодня 2", stats["today"] == 2)
    check("статистика: в работе 1", stats["in_progress"] == 1)


async def test_export(tmp: Path) -> None:
    print("\n[3/5] Выгрузка в Excel")
    path = await export_applications(tmp / "exports")

    check("файл создан", path.exists(), str(path))
    check("расширение .xlsx", path.suffix == ".xlsx")

    workbook = load_workbook(path)
    check("лист «Заявки» есть", "Заявки" in workbook.sheetnames, str(workbook.sheetnames))
    check("лист «Сводка» есть", "Сводка" in workbook.sheetnames)

    sheet = workbook["Заявки"]
    check("заголовков 8", sheet.max_column == 8, str(sheet.max_column))
    check("строк с данными 3 (шапка + 2 заявки)", sheet.max_row == 3, str(sheet.max_row))
    check("первая колонка шапки — «№»", sheet.cell(row=1, column=1).value == "№")
    check("имя первого клиента на месте", sheet.cell(row=2, column=3).value == "Иван Петров")
    check("статус выгружен по-русски", sheet.cell(row=2, column=6).value == "В работе")

    summary = workbook["Сводка"]
    check("в сводке есть «Всего заявок»", summary.cell(row=3, column=1).value == "Всего заявок")
    check("в сводке всего 2", summary.cell(row=3, column=2).value == 2)

    workbook.close()


def test_keyboards() -> None:
    print("\n[4/5] Клавиатуры")
    check("главное меню собирается", main_menu() is not None)
    check("подтверждение заявки собирается", confirm_menu() is not None)
    check("меню админа собирается", admin_menu() is not None)


def test_handlers_import() -> None:
    print("\n[5/6] Сборка роутеров")
    from bot.handlers import admin, client

    check("роутер клиента создан", client.router.name == "client")
    check("роутер админов создан", admin.router.name == "admin")
    check(
        "у клиента есть хендлеры",
        len(client.router.message.handlers) > 0,
        str(len(client.router.message.handlers)),
    )
    check(
        "у админов есть callback-хендлеры",
        len(admin.router.callback_query.handlers) > 0,
        str(len(admin.router.callback_query.handlers)),
    )

    message_handlers = {h.callback.__name__ for h in client.router.message.handlers}
    callback_handlers = {
        h.callback.__name__ for h in client.router.callback_query.handlers
    }

    check(
        "есть запасной ответ на непонятное сообщение",
        "fallback" in message_handlers,
        str(sorted(message_handlers)),
    )
    check(
        "есть ответ на устаревшую кнопку заявки",
        "stale_callback" in callback_handlers,
        str(sorted(callback_handlers)),
    )
    check(
        "все шаги формы зарегистрированы",
        {
            "process_name",
            "process_phone",
            "process_comment",
            "confirm_application",
            "edit_phone",
        }
        <= message_handlers | callback_handlers,
        str(sorted(message_handlers | callback_handlers)),
    )

    # Корневой фильтр на роутере клиента не должен пускать сообщения из групп
    client_root_filters = client.router.message._handler.filters or []
    check(
        "клиентский роутер ограничен личными чатами",
        len(client_root_filters) > 0,
        "корневых фильтров нет",
    )
    admin_root_filters = admin.router.message._handler.filters or []
    check(
        "админский роутер закрыт фильтром доступа",
        len(admin_root_filters) > 0,
        "корневых фильтров нет",
    )

    # Проверяем, что карточка заявки и список строятся без данных
    check("список заявок собирается", applications_list([], status="all", page=0, total=0) is not None)
    check("карточка заявки собирается", application_card(1) is not None)


async def test_access_filter() -> None:
    """Доступ к админ-панели — самое критичное место, проверяем отдельно."""
    print("\n[6/6] Доступ к админ-панели")

    from types import SimpleNamespace

    from bot.config import Config, _parse_admin_ids
    from bot.handlers.admin import IsAdmin

    check("ADMIN_IDS разбирается", _parse_admin_ids("111, 222") == [111, 222])
    check("мусор в ADMIN_IDS пропускается", _parse_admin_ids("111, abc, ") == [111])
    check("точка с запятой работает", _parse_admin_ids("111;222") == [111, 222])

    config = Config(bot_token="test", admin_ids=[111])
    admin_event = SimpleNamespace(from_user=SimpleNamespace(id=111))
    stranger_event = SimpleNamespace(from_user=SimpleNamespace(id=222))
    anonymous_event = SimpleNamespace(from_user=None)

    is_admin = IsAdmin()
    check("админ проходит", await is_admin(admin_event, config=config) is True)
    check("посторонний не проходит", await is_admin(stranger_event, config=config) is False)
    check("без from_user не проходит", await is_admin(anonymous_event, config=config) is False)

    empty_config = Config(bot_token="test", admin_ids=[])
    check(
        "при пустом ADMIN_IDS не проходит никто",
        await is_admin(admin_event, config=empty_config) is False,
    )

    check("конфиг без токена невалиден", Config(bot_token="", admin_ids=[1]).is_valid is False)
    check("конфиг с токеном валиден", Config(bot_token="abc", admin_ids=[1]).is_valid is True)
    check(
        "конфиг сообщает о проблемах",
        len(Config(bot_token="", admin_ids=[]).problems()) == 2,
        str(Config(bot_token="", admin_ids=[]).problems()),
    )


async def main() -> int:
    print("=" * 60)
    print("Смоук-тест Telegram-бота приёма заявок")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        test_validators()
        await test_database(tmp)
        await test_export(tmp)
        test_keyboards()
        test_handlers_import()
        await test_access_filter()
        await db.close_db()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"ПРОВАЛЕНО: {len(FAILURES)} из {CHECKS}")
        for name in FAILURES:
            print(f"  • {name}")
        return 1

    print(f"ВСЁ ХОРОШО: {CHECKS} проверок пройдено")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
