import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.filters import Command
from aiogram.methods import TelegramMethod
from aiogram.methods.base import Response
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import async_session
from backend.app.logging_utils import configure_logging, log_environment, log_settings
from backend.app.models import User, Appointment, Clinic

configure_logging()
logger = logging.getLogger("bot")


class LoggingSessionMiddleware(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: Callable[[Bot, TelegramMethod], Awaitable[Response]],
        bot: Bot,
        method: TelegramMethod,
    ) -> Response:
        method_name = type(method).__name__
        logger.info("Telegram API --> %s", method_name)
        start = time.monotonic()
        try:
            result = await make_request(bot, method)
        except Exception:
            duration_ms = (time.monotonic() - start) * 1000
            logger.exception("Telegram API <-- %s ERROR (%.1f ms)", method_name, duration_ms)
            raise
        duration_ms = (time.monotonic() - start) * 1000
        logger.info("Telegram API <-- %s OK (%.1f ms)", method_name, duration_ms)
        return result


bot = Bot(token=settings.BOT_TOKEN)
bot.session.middleware(LoggingSessionMiddleware())
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")


@dp.update.outer_middleware()
async def log_updates(
    handler: Callable[[types.Update, Dict[str, Any]], Awaitable[Any]],
    event: types.Update,
    data: Dict[str, Any],
) -> Any:
    user_id = None
    payload_kind = "other"
    if event.message:
        payload_kind = "message"
        user_id = event.message.from_user.id if event.message.from_user else None
    elif event.callback_query:
        payload_kind = "callback_query"
        user_id = event.callback_query.from_user.id if event.callback_query.from_user else None
    elif event.inline_query:
        payload_kind = "inline_query"
        user_id = event.inline_query.from_user.id if event.inline_query.from_user else None
    logger.info("Update %s: kind=%s user=%s", event.update_id, payload_kind, user_id)
    start = time.monotonic()
    try:
        result = await handler(event, data)
    except Exception:
        duration_ms = (time.monotonic() - start) * 1000
        logger.exception("Update %s handler ERROR (%.1f ms)", event.update_id, duration_ms)
        raise
    duration_ms = (time.monotonic() - start) * 1000
    logger.info("Update %s done (%.1f ms)", event.update_id, duration_ms)
    return result

def is_https_url(url: str) -> bool:
    return url.startswith("https://")

async def get_db():
    async with async_session() as session:
        yield session

async def send_remind(chat_id: int, appointment_id: int):
    async with async_session() as db:
        result = await db.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
        appointment = result.scalar_one_or_none()
        if not appointment or appointment.status != "scheduled":
            return

    await bot.send_message(
        chat_id, 
        "🔔 **Напоминание:**\nНе забудьте завтра взять с собой паспорт и направление на анализы!\n"
        f"Ваша запись на {appointment.slot_datetime.strftime('%d.%m.%Y %H:%M')}"
    )

async def schedule_appointment_reminder(chat_id: int, appointment_id: int, slot_datetime: datetime):
    # ТЗ FR-27: напоминание за 3 часа
    remind_at = slot_datetime - timedelta(hours=3)
    
    if remind_at < datetime.now():
        # Если до приема меньше 3 часов, напомним через минуту
        remind_at = datetime.now() + timedelta(minutes=1)
        
    job_id = f"remind_{appointment_id}"
    try:
        scheduler.remove_job(job_id)
    except:
        pass
        
    scheduler.add_job(
        send_remind,
        "date",
        run_date=remind_at,
        args=[chat_id, appointment_id],
        id=job_id
    )

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

    name = message.from_user.first_name
    await message.answer(
        f"Добро пожаловать, {name}!\n\n"
        "Для использования сервиса необходимо ваше согласие на обработку персональных данных "
        "в соответствии с Федеральным законом № 152-ФЗ.",
        reply_markup=get_main_kb()
    )

@dp.message(Command("paysupport"))
async def pay_support_handler(message: types.Message):
    await message.answer(
        "🛠 **Поддержка платежей**\n\n"
        "Если у вас возникли проблемы с оплатой или начислением баллов, "
        "пожалуйста, напишите нашему оператору: @admin_handle"
    )

def get_main_kb():
    open_button = (
        InlineKeyboardButton(
            text="🏥 Открыть приложение",
            web_app=WebAppInfo(url=settings.WEB_APP_URL)
        )
        if is_https_url(settings.WEB_APP_URL)
        else InlineKeyboardButton(
            text="🏥 Открыть приложение",
            url=settings.WEB_APP_URL
        )
    )
    kb = [
        [open_button],
        [InlineKeyboardButton(text="🆘 Написать нам", url="https://t.me/admin_handle")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def main():
    logger.info("Starting bot...")
    log_environment(logger)
    log_settings(logger, settings)

    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="paysupport", description="🛠 Поддержка платежей")
    ])

    if is_https_url(settings.WEB_APP_URL):
        await bot.set_chat_menu_button(
            menu_button=types.MenuButtonWebApp(
                text="Записаться",
                web_app=WebAppInfo(url=settings.WEB_APP_URL)
            )
        )

    scheduler.start()
    logger.info("=== Bot готов к работе ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
