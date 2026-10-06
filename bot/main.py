"""Точка входа: собирает конфиг, поднимает базу, запускает polling.

Запуск:
    python -m bot.main
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot import db
from bot.config import load_config
from bot.handlers import admin, client

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # Логи aiogram на уровне INFO слишком шумные при обычной работе
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def set_commands(bot: Bot) -> None:
    """Меню команд в интерфейсе Telegram."""
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать работу"),
            BotCommand(command="help", description="Что умеет бот"),
            BotCommand(command="cancel", description="Отменить заполнение заявки"),
        ]
    )


async def main() -> None:
    setup_logging()
    config = load_config()

    problems = config.problems()
    if not config.is_valid:
        for problem in problems:
            logger.error(problem)
        logger.error("Заполните .env по образцу .env.example и запустите снова.")
        raise SystemExit(1)

    for problem in problems:
        logger.warning(problem)

    await db.init_db(config.db_path)
    logger.info("База данных: %s", config.db_path)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # MemoryStorage: состояния диалогов живут в памяти и сбрасываются при
    # перезапуске. Для приёма заявок этого достаточно — незавершённая заявка
    # просто заполняется заново. Для долгих сценариев хранилище меняется
    # на Redis одной строкой.
    dispatcher = Dispatcher(storage=MemoryStorage(), config=config)

    # Роутер админов подключаем первым: его хендлеры специфичнее
    dispatcher.include_router(admin.router)
    dispatcher.include_router(client.router)

    await set_commands(bot)

    me = await bot.get_me()
    logger.info("Бот запущен: @%s", me.username)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        await db.close_db()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as exc:
        # Ctrl+C — штатное завершение, не показываем стек
        if isinstance(exc, SystemExit) and exc.code not in (0, None):
            sys.exit(exc.code)
