import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.methods.base import Response
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import async_session, engine
from backend.app.logging_utils import configure_logging, log_environment, log_settings
from backend.app.models import Base, User, Appointment, Clinic, BotAppointmentRequest

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
dp = Dispatcher(storage=MemoryStorage())
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
        await enable_webapp_button(message.from_user.id)
        await message.answer(
            f"Добро пожаловать, {name}! 👋\n\n"
            "Вы можете пользоваться всеми функциями сервиса.",
            reply_markup=get_main_kb(message.from_user.id),
        )
        return

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

    await enable_webapp_button(callback.from_user.id)
    await callback.message.edit_text(
        "✅ Согласие на обработку персональных данных принято.",
        parse_mode="HTML",
    )
    await callback.message.answer(
        f"Добро пожаловать, {callback.from_user.first_name or 'друг'}! 👋\n\n"
        "Теперь вам доступен полный функционал сервиса «Иду к врачу»! 🏥",
        reply_markup=get_main_kb(callback.from_user.id),
    )
    await callback.answer()


@dp.message(Command("paysupport"))
async def pay_support_handler(message: types.Message):
    await message.answer(
        "🛠 **Поддержка платежей**\n\n"
        "Если у вас возникли проблемы с оплатой или начислением баллов, "
        "пожалуйста, напишите нашему оператору: @admin_handle"
    )


# Скрытая команда: не регистрируется в set_my_commands, поэтому не отображается
# в подсказках Telegram, но сработает, если её ввести вручную.
@dp.message(Command("admin"))
async def admin_link_handler(message: types.Message):
    url = settings.WEB_APP_URL.rstrip("/") + "/admin"
    if is_https_url(settings.WEB_APP_URL):
        button = InlineKeyboardButton(text="🛠 Открыть админ-панель", web_app=WebAppInfo(url=url))
    else:
        button = InlineKeyboardButton(text="🛠 Открыть админ-панель", url=url)
    await message.answer(
        f"🔐 <b>Админ-панель</b>\n\n"
        f"<a href=\"{url}\">{url}</a>\n\n"
        "Для входа требуются логин и пароль администратора.",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[button]]),
    )

def get_consent_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать", callback_data="consent_agree")],
        [InlineKeyboardButton(text="📄 Подробнее о согласии", callback_data="consent_view")],
    ])


def _append_tg_id(path: str, tg_id: int) -> str:
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}tg_id={tg_id}"


def get_main_kb(tg_id: int | None = None):
    def webapp_btn(text: str, path: str = "") -> InlineKeyboardButton:
        full_path = _append_tg_id(path, tg_id) if tg_id else path
        url = settings.WEB_APP_URL + full_path
        if is_https_url(settings.WEB_APP_URL):
            return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))
        return InlineKeyboardButton(text=text, url=url)

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🏥 Сервис "Иду к врачу"', url="https://example.com")],
        [webapp_btn("📚 Подготовка")],
        [webapp_btn("📅 Записаться к врачу", "/booking.html")],
        [webapp_btn("📋 Мои записи", "/booking.html?screen=appointments")],
        [InlineKeyboardButton(text="✉️ Написать нам", url="https://t.me/admin_handle")],
    ])

# ── Запись к врачу ──────────────────────────────────────────────────────────

class ApptStates(StatesGroup):
    choosing_city = State()
    choosing_clinic = State()
    choosing_date = State()
    choosing_time = State()
    confirming = State()

CITIES = {"moscow": "Москва"}
CLINICS = {"zubnaya_feya": "🦷 Зубная фея"}
TIME_RANGES = ["8:00–10:00", "10:00–12:00", "12:00–14:00",
               "14:00–16:00", "16:00–18:00", "18:00–20:00"]


def _appt_city_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Москва", callback_data="appt_city:moscow")],
        [InlineKeyboardButton(text="✖ Отмена", callback_data="appt_cancel")],
    ])


def _appt_clinic_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🦷 Зубная фея", callback_data="appt_clinic:zubnaya_feya")],
        [InlineKeyboardButton(text="← Назад", callback_data="appt_back_city")],
    ])


def _appt_date_kb() -> InlineKeyboardMarkup:
    today = datetime.now().date()
    rows = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        label = d.strftime("%d.%m (%a)").replace(
            "Mon", "пн").replace("Tue", "вт").replace("Wed", "ср").replace(
            "Thu", "чт").replace("Fri", "пт").replace("Sat", "сб").replace("Sun", "вс")
        rows.append([InlineKeyboardButton(text=label, callback_data=f"appt_date:{d.isoformat()}")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="appt_back_clinic")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _appt_time_kb() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(TIME_RANGES), 2):
        pair = TIME_RANGES[i:i+2]
        rows.append([
            InlineKeyboardButton(text=t, callback_data=f"appt_time:{t}") for t in pair
        ])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="appt_back_date")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _appt_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="appt_confirm")],
        [InlineKeyboardButton(text="← Назад", callback_data="appt_back_time")],
    ])


@dp.callback_query(F.data == "appt_start")
async def appt_start(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("🏙 Выберите город:", reply_markup=_appt_city_kb())
    await state.set_state(ApptStates.choosing_city)
    await callback.answer()


@dp.callback_query(F.data.startswith("appt_city:"), ApptStates.choosing_city)
async def appt_city(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    await state.update_data(city=CITIES[key])
    await callback.message.edit_text("🏥 Выберите клинику:", reply_markup=_appt_clinic_kb())
    await state.set_state(ApptStates.choosing_clinic)
    await callback.answer()


@dp.callback_query(F.data == "appt_back_city")
async def appt_back_city(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🏙 Выберите город:", reply_markup=_appt_city_kb())
    await state.set_state(ApptStates.choosing_city)
    await callback.answer()


@dp.callback_query(F.data.startswith("appt_clinic:"), ApptStates.choosing_clinic)
async def appt_clinic(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    await state.update_data(clinic=CLINICS[key])
    await callback.message.edit_text("📅 Выберите удобную дату:", reply_markup=_appt_date_kb())
    await state.set_state(ApptStates.choosing_date)
    await callback.answer()


@dp.callback_query(F.data == "appt_back_clinic")
async def appt_back_clinic(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🏥 Выберите клинику:", reply_markup=_appt_clinic_kb())
    await state.set_state(ApptStates.choosing_clinic)
    await callback.answer()


@dp.callback_query(F.data.startswith("appt_date:"), ApptStates.choosing_date)
async def appt_date(callback: types.CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":", 1)[1]
    d = datetime.fromisoformat(date_str)
    await state.update_data(date=d.strftime("%d.%m.%Y"), date_iso=date_str)
    await callback.message.edit_text("🕐 Выберите диапазон времени:", reply_markup=_appt_time_kb())
    await state.set_state(ApptStates.choosing_time)
    await callback.answer()


@dp.callback_query(F.data == "appt_back_date")
async def appt_back_date(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📅 Выберите удобную дату:", reply_markup=_appt_date_kb())
    await state.set_state(ApptStates.choosing_date)
    await callback.answer()


@dp.callback_query(F.data.startswith("appt_time:"), ApptStates.choosing_time)
async def appt_time(callback: types.CallbackQuery, state: FSMContext):
    time_range = callback.data.split(":", 1)[1]
    await state.update_data(time_range=time_range)
    data = await state.get_data()
    summary = (
        "📋 <b>Проверьте вашу заявку:</b>\n\n"
        f"🏙 Город: {data['city']}\n"
        f"🏥 Клиника: {data['clinic']}\n"
        f"📅 Дата: {data['date']}\n"
        f"🕐 Время: {data['time_range']}\n\n"
        "<i>Администратор клиники свяжется с вами для уточнения и согласования даты и времени записи.</i>"
    )
    await callback.message.edit_text(summary, parse_mode="HTML", reply_markup=_appt_confirm_kb())
    await state.set_state(ApptStates.confirming)
    await callback.answer()


@dp.callback_query(F.data == "appt_back_time")
async def appt_back_time(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("🕐 Выберите диапазон времени:", reply_markup=_appt_time_kb())
    await state.set_state(ApptStates.choosing_time)
    await callback.answer()


@dp.callback_query(F.data == "appt_confirm", ApptStates.confirming)
async def appt_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    async with async_session() as db:
        result = await db.execute(select(User).where(User.telegram_id == callback.from_user.id))
        user = result.scalar_one_or_none()
        if user:
            req = BotAppointmentRequest(
                user_id=user.id,
                city=data["city"],
                clinic_name=data["clinic"],
                desired_date=data["date"],
                time_range=data["time_range"],
            )
            db.add(req)
            await db.commit()

    await callback.message.edit_text(
        "✅ <b>Заявка отправлена!</b>\n\n"
        f"🏥 {data['clinic']}, {data['city']}\n"
        f"📅 {data['date']}, {data['time_range']}\n\n"
        "Администратор клиники свяжется с вами для уточнения и согласования даты и времени записи.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Мои записи", callback_data="my_appts")],
            [InlineKeyboardButton(text="🏠 На главную", callback_data="go_home")],
        ]),
    )
    await callback.answer()


@dp.callback_query(F.data == "appt_cancel")
async def appt_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer()


@dp.callback_query(F.data == "go_home")
async def go_home(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🏠 Главное меню",
        reply_markup=get_main_kb(callback.from_user.id),
    )
    await callback.answer()


# ── Мои записи ──────────────────────────────────────────────────────────────

STATUS_LABELS = {"pending": "⏳ Ожидает подтверждения", "cancelled": "❌ Отменена"}


def _my_appt_kb(appt_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Перенести", callback_data=f"appt_reschedule:{appt_id}"),
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"appt_cancel_req:{appt_id}"),
        ],
    ])


@dp.callback_query(F.data == "my_appts")
async def my_appts_handler(callback: types.CallbackQuery):
    await callback.answer()
    try:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.telegram_id == callback.from_user.id))
            user = result.scalar_one_or_none()
            if not user:
                await callback.message.answer("Пользователь не найден.")
                return

            result = await db.execute(
                select(BotAppointmentRequest)
                .where(BotAppointmentRequest.user_id == user.id,
                       BotAppointmentRequest.status != "cancelled")
                .order_by(BotAppointmentRequest.created_at.desc())
            )
            appts = result.scalars().all()

        if not appts:
            await callback.message.answer(
                "📋 <b>Мои записи</b>\n\nУ вас нет активных заявок.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 На главную", callback_data="go_home")],
                ]),
            )
            return

        for appt in appts:
            status = STATUS_LABELS.get(appt.status, appt.status)
            text = (
                f"📋 <b>Заявка №{appt.id}</b>\n\n"
                f"🏥 {appt.clinic_name}, {appt.city}\n"
                f"📅 {appt.desired_date}, {appt.time_range}\n"
                f"Статус: {status}"
            )
            await callback.message.answer(text, parse_mode="HTML", reply_markup=_my_appt_kb(appt.id))

        await callback.message.answer(
            "Выберите запись для управления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 На главную", callback_data="go_home")],
            ]),
        )
    except Exception:
        logger.exception("my_appts_handler error user=%s", callback.from_user.id)
        await callback.message.answer("Произошла ошибка. Попробуйте позже.")


@dp.callback_query(F.data.startswith("appt_cancel_req:"))
async def appt_cancel_req(callback: types.CallbackQuery):
    appt_id = int(callback.data.split(":", 1)[1])
    async with async_session() as db:
        result = await db.execute(
            select(BotAppointmentRequest).where(BotAppointmentRequest.id == appt_id)
        )
        appt = result.scalar_one_or_none()
        if appt:
            appt.status = "cancelled"
            await db.commit()

    await callback.message.edit_text(
        f"❌ Заявка №{appt_id} отменена.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 На главную", callback_data="go_home")],
        ]),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("appt_reschedule:"))
async def appt_reschedule(callback: types.CallbackQuery, state: FSMContext):
    appt_id = int(callback.data.split(":", 1)[1])
    async with async_session() as db:
        result = await db.execute(
            select(BotAppointmentRequest).where(BotAppointmentRequest.id == appt_id)
        )
        appt = result.scalar_one_or_none()
        if appt:
            appt.status = "cancelled"
            await db.commit()

    await state.clear()
    await callback.message.answer("🏙 Выберите город для новой записи:", reply_markup=_appt_city_kb())
    await state.set_state(ApptStates.choosing_city)
    await callback.answer()


async def enable_webapp_button(chat_id: int):
    if is_https_url(settings.WEB_APP_URL):
        await bot.set_chat_menu_button(
            chat_id=chat_id,
            menu_button=types.MenuButtonWebApp(
                text="Записаться",
                web_app=WebAppInfo(url=settings.WEB_APP_URL),
            ),
        )

async def main():
    logger.info("Starting bot...")
    log_environment(logger)
    log_settings(logger, settings)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB tables ensured")

    await call_with_retry(
        "set_my_commands",
        lambda: bot.set_my_commands([
            BotCommand(command="start", description="🏠 Главное меню"),
            BotCommand(command="paysupport", description="🛠 Поддержка платежей"),
        ]),
    )

    await call_with_retry(
        "set_chat_menu_button",
        lambda: bot.set_chat_menu_button(
            menu_button=types.MenuButtonCommands()
        ),
    )

    scheduler.start()
    logger.info("=== Bot готов к работе ===")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
