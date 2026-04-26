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

async def call_with_retry(
    op_name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> Any:
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            result = await coro_factory()
            if attempt > 1:
                logger.info("%s: успех с попытки %d/%d", op_name, attempt, attempts)
            return result
        except Exception as exc:
            last_exc = exc
            if attempt == attempts:
                logger.error(
                    "%s: исчерпаны %d попыток, последняя ошибка: %r",
                    op_name, attempts, exc,
                )
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            logger.warning(
                "%s: попытка %d/%d не удалась (%r), повтор через %.1f с",
                op_name, attempt, attempts, exc, delay,
            )
            await asyncio.sleep(delay)
    raise last_exc  # unreachable


async def send_remind(chat_id: int, appointment_id: int):
    try:
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
    except Exception:
        logger.exception(
            "send_remind: ошибка отправки напоминания chat_id=%s appointment_id=%s",
            chat_id, appointment_id,
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

INFO_MESSAGE = (
    "Привет! Я цифровой помощник «Иду к врачу».\n"
    "Я помогу ребёнку с РАС подготовиться к посещению врача и сделать его менее тревожным.\n\n"
    "<b>Что доступно прямо сейчас:</b>\n"
    "• Подготовка ребёнка к посещению стоматолога\n"
    "• Подготовка к сдаче крови\n"
    "• Запись в клинику\n\n"
    "Подготовка включает адаптационные материалы: мультфильмы, социстории, "
    "игры-тренажёры и рекомендации для родителей.\n\n"
    "<i>Нажимая кнопку «Начать», вы подтверждаете согласие на обработку "
    "персональных данных в соответствии с ФЗ-152.</i>"
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
                first_name=message.from_user.first_name,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

    name = message.from_user.first_name or "друг"

    if user.consent_timestamp:
        await message.answer(
            f"Добро пожаловать, {name}! 👋\n\n"
            "Вы можете пользоваться всеми функциями сервиса.",
            reply_markup=get_main_kb(),
        )
        return

    await message.answer(f"Добро пожаловать, {name}!")
    await message.answer(
        INFO_MESSAGE,
        parse_mode="HTML",
        reply_markup=get_consent_kb(),
    )

CONSENT_TEXT = (
    "📋 <b>Согласие на обработку персональных данных</b>\n\n"
    "В соответствии с Федеральным законом от 27.07.2006 № 152-ФЗ «О персональных данных».\n\n"
    "<b>Оператор:</b> Сервис «Иду к врачу»\n\n"
    "<b>Цели обработки:</b>\n"
    "• предоставление доступа к материалам сервиса;\n"
    "• идентификация пользователя в Telegram;\n"
    "• обработка обращений в поддержку;\n"
    "• совершенствование работы сервиса.\n\n"
    "<b>Обрабатываемые данные:</b>\n"
    "• Telegram ID, имя и username;\n"
    "• действия в приложении (просмотренные материалы, прогресс).\n\n"
    "<b>Передача третьим лицам:</b> не осуществляется, кроме случаев, "
    "предусмотренных законодательством РФ.\n\n"
    "<b>Срок действия:</b> с момента согласия до его отзыва. "
    "Для отзыва напишите в поддержку.\n\n"
    "<b>Ваши права:</b> уточнение, блокирование и уничтожение данных "
    "по обращению к Оператору; жалоба в Роскомнадзор."
)


@dp.callback_query(F.data == "consent_view")
async def consent_view_handler(callback: types.CallbackQuery):
    await callback.message.answer(
        CONSENT_TEXT,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Назад", callback_data="consent_back")],
        ]),
    )
    await callback.answer()


@dp.callback_query(F.data == "consent_back")
async def consent_back_handler(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(F.data == "consent_agree")
async def consent_agree_handler(callback: types.CallbackQuery):
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                first_name=callback.from_user.first_name,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        if not user.consent_timestamp:
            user.consent_version = "1.0"
            user.consent_timestamp = datetime.utcnow()
            await db.commit()
            logger.info("consent: принято telegram_id=%s", callback.from_user.id)

    await callback.message.edit_text(
        "✅ Согласие на обработку персональных данных принято.",
        parse_mode="HTML",
    )
    await callback.message.answer(
        f"Добро пожаловать, {callback.from_user.first_name or 'друг'}! 👋\n\n"
        "Теперь вам доступен полный функционал сервиса «Иду к врачу»! 🏥",
        reply_markup=get_main_kb(),
    )
    await callback.answer()


@dp.message(Command("paysupport"))
async def pay_support_handler(message: types.Message):
    await message.answer(
        "🛠 **Поддержка платежей**\n\n"
        "Если у вас возникли проблемы с оплатой или начислением баллов, "
        "пожалуйста, напишите нашему оператору: @admin_handle"
    )

def get_consent_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать", callback_data="consent_agree")],
        [InlineKeyboardButton(text="📄 Подробнее о согласии", callback_data="consent_view")],
    ])


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

    await call_with_retry(
        "set_my_commands",
        lambda: bot.set_my_commands([
            BotCommand(command="start", description="🏠 Главное меню"),
            BotCommand(command="paysupport", description="🛠 Поддержка платежей"),
        ]),
    )

    if is_https_url(settings.WEB_APP_URL):
        await call_with_retry(
            "set_chat_menu_button",
            lambda: bot.set_chat_menu_button(
                menu_button=types.MenuButtonWebApp(
                    text="Записаться",
                    web_app=WebAppInfo(url=settings.WEB_APP_URL),
                )
            ),
        )

    scheduler.start()
    logger.info("=== Bot готов к работе ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
