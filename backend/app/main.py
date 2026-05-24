import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from .auth import validate_init_data
from .config import settings
from .database import ensure_storage, get_db
from .logging_utils import configure_logging, log_environment, log_settings
from .mis import mis_provider
from .models import (
    AdminAuditLog,
    AdminNotification,
    AdminRole,
    AdminUser,
    Appointment,
    BotAppointmentRequest,
    ChildProfile,
    City,
    Clinic,
    ContentItem,
    ContentModule,
    Direction,
    Doctor,
    DoctorSchedule,
    ParentProfile,
    Progress,
    Purchase,
    Service,
    SupportTicket,
    User,
)
from .schemas import (
    AdminCityCreate,
    AdminCityItem,
    AdminCityUpdate,
    AdminClinicCreate,
    AdminClinicItem,
    AdminClinicUpdate,
    AdminContentCreate,
    AdminContentItem,
    AdminContentUpdate,
    AdminDirectionCreate,
    AdminDirectionItem,
    AdminDirectionUpdate,
    AdminDoctorCreate,
    AdminDoctorItem,
    AdminDoctorUpdate,
    AdminAppointmentItem,
    AdminLoginRequest,
    AdminMe,
    AdminNotificationItem,
    AdminRoleCreate,
    AdminRoleItem,
    AdminRoleUpdate,
    AdminScheduleUpdate,
    AdminServiceCreate,
    AdminServiceItem,
    AdminServiceUpdate,
    AdminStats,
    AdminUserCreate,
    AdminUserItem,
    AdminUserUpdate,
    Appointment as AppointmentSchema,
    AppointmentCreate,
    AppointmentDetail,
    AppointmentReschedule,
    City as CitySchema,
    Clinic as ClinicSchema,
    Doctor as DoctorSchema,
    DoctorSlot,
    ProfileResponse,
    ProfileSaveRequest,
    Service as ServiceSchema,
    SlotSchema,
    SupportTicket as SupportTicketSchema,
    SupportTicketCreate,
    User as UserSchema,
)

configure_logging()
logger = logging.getLogger("backend.api")

app = FastAPI(title="Иду к врачу API")


# ── Middleware ────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    client = request.client.host if request.client else "-"
    logger.info("--> %s %s from %s", request.method, request.url.path, client)
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.monotonic() - start) * 1000
        logger.exception("<-- %s %s ERROR (%.1f ms)", request.method, request.url.path, duration_ms)
        raise
    duration_ms = (time.monotonic() - start) * 1000
    logger.info("<-- %s %s %s (%.1f ms)", request.method, request.url.path, response.status_code, duration_ms)
    return response


templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
app.mount("/styles", StaticFiles(directory=os.path.join(BASE_DIR, "frontend", "styles")), name="styles")
app.mount("/materials", StaticFiles(directory=os.path.join(BASE_DIR, "frontend", "materials")), name="materials")
app.mount("/frontend", StaticFiles(directory=os.path.join(BASE_DIR, "frontend")), name="frontend")


def _run_migrations() -> None:
    cfg = Config(os.path.join(BASE_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BASE_DIR, "migrations"))
    command.upgrade(cfg, "head")


@app.on_event("startup")
async def startup():
    logger.info("Starting backend...")
    log_environment(logger)
    log_settings(logger, settings)
    ensure_storage()
    await asyncio.get_running_loop().run_in_executor(None, _run_migrations)
    from .seed import seed_if_empty
    await seed_if_empty()
    logger.info("=== Backend готов к работе ===")


# ── Static pages ──────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(os.path.join(BASE_DIR, "frontend", "index.html"))

@app.get("/booking.html", include_in_schema=False)
async def booking():
    return FileResponse(os.path.join(BASE_DIR, "frontend", "booking.html"))

@app.get("/admin", include_in_schema=False)
async def admin_panel():
    return FileResponse(os.path.join(BASE_DIR, "frontend", "admin.html"))


# ── Telegram user auth ────────────────────────────────────────

async def get_current_user(x_tg_init_data: str = Header(...), db: AsyncSession = Depends(get_db)) -> User:
    if not validate_init_data(x_tg_init_data):
        raise HTTPException(status_code=401, detail="Invalid initData")

    try:
        from urllib.parse import parse_qs
        params = parse_qs(x_tg_init_data)
        user_json = params.get("user", [None])[0]
        if not user_json:
            if settings.DEBUG:
                tg_id = 12345678
                logger.warning("auth: поле 'user' отсутствует — подставлен debug telegram_id=%s", tg_id)
            else:
                raise HTTPException(status_code=401, detail="User info missing")
        else:
            user_data = json.loads(user_json)
            tg_id = user_data.get("id")
    except Exception:
        if settings.DEBUG:
            tg_id = 12345678
            logger.warning("auth: ошибка парсинга initData — debug telegram_id=%s", tg_id, exc_info=True)
        else:
            raise HTTPException(status_code=401, detail="Invalid user data")

    result = await db.execute(select(User).where(User.telegram_id == tg_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=tg_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


# ── Admin token auth ──────────────────────────────────────────

_BEARER = HTTPBearer()


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


# Slot_datetime is stored as naive UTC. Display in Moscow time (UTC+3, no DST).
MSK_OFFSET = timedelta(hours=3)

def _fmt_msk(d: datetime) -> str:
    return (d + MSK_OFFSET).strftime('%d.%m.%Y %H:%M')


def _make_admin_token(admin_id: int) -> str:
    exp = int(time.time()) + 86400 * 7
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": admin_id, "exp": exp}).encode()
    ).decode().rstrip("=")
    sig = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_admin_token(token: str) -> Optional[int]:
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(settings.SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padding = "=" * (4 - len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        if data["exp"] < time.time():
            return None
        sub = data.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None


async def get_admin(
    creds: HTTPAuthorizationCredentials = Depends(_BEARER),
    db: AsyncSession = Depends(get_db),
) -> AdminUser:
    admin_id = _verify_admin_token(creds.credentials)
    if admin_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    admin = (await db.execute(select(AdminUser).where(AdminUser.id == admin_id))).scalar_one_or_none()
    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail="Admin disabled or not found")
    return admin


async def require_super(admin: AdminUser = Depends(get_admin)) -> AdminUser:
    if not admin.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin required")
    return admin


def _ensure_clinic_access(admin: AdminUser, clinic_id: Optional[int]) -> None:
    """Clinic admins can only touch their own clinic."""
    if admin.is_superadmin:
        return
    if admin.clinic_id is None:
        raise HTTPException(status_code=403, detail="Admin has no clinic assigned")
    if clinic_id is None or clinic_id != admin.clinic_id:
        raise HTTPException(status_code=403, detail="Forbidden: foreign clinic")


# ── Public API ────────────────────────────────────────────────

@app.get("/api/cities", response_model=List[CitySchema])
async def get_cities(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(City).where(City.is_active == True))
    return result.scalars().all()

@app.get("/api/clinics", response_model=List[ClinicSchema])
async def get_clinics(city_id: int, db: AsyncSession = Depends(get_db)):
    clinics = (await db.execute(
        select(Clinic).where(Clinic.city_id == city_id, Clinic.is_active == True)
    )).scalars().all()
    if not clinics:
        return []
    clinic_ids = [c.id for c in clinics]
    svc_rows = (await db.execute(
        select(Service.id, Direction.clinic_id)
        .join(Direction, Service.direction_id == Direction.id)
        .where(
            Direction.clinic_id.in_(clinic_ids),
            Service.is_active == True,
            Direction.is_active == True,
        )
    )).all()
    by_clinic: Dict[int, List[int]] = {cid: [] for cid in clinic_ids}
    for svc_id, cid in svc_rows:
        by_clinic.setdefault(cid, []).append(svc_id)
    return [
        ClinicSchema(
            id=c.id, name=c.name, city_id=c.city_id, address=c.address,
            phone=c.phone, worktime=c.worktime, is_active=c.is_active,
            service_ids=by_clinic.get(c.id, []),
        )
        for c in clinics
    ]


@app.get("/api/services", response_model=List[ServiceSchema])
async def get_services(clinic_id: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Service, Direction)
        .join(Direction, Service.direction_id == Direction.id)
        .where(Service.is_active == True, Direction.is_active == True)
    )
    if clinic_id is not None:
        stmt = stmt.where(Direction.clinic_id == clinic_id)
    rows = (await db.execute(stmt)).all()
    return [
        ServiceSchema(
            id=s.id, clinic_id=d.clinic_id, direction_id=d.id,
            direction_name=d.name, direction_icon=d.icon,
            name=s.name, description=s.description, icon=s.icon,
            service_type=s.service_type, is_active=s.is_active,
        )
        for s, d in rows
    ]

@app.get("/api/doctors", response_model=List[DoctorSchema])
async def get_doctors(clinic_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Doctor).where(Doctor.clinic_id == clinic_id, Doctor.is_active == True)
    )
    return result.scalars().all()


@app.get("/api/doctors/{doctor_id}/slots", response_model=List[DoctorSlot])
async def get_doctor_slots(doctor_id: int, date: str, db: AsyncSession = Depends(get_db)):
    doctor = (await db.execute(select(Doctor).where(Doctor.id == doctor_id))).scalar_one_or_none()
    if not doctor or not doctor.is_active:
        raise HTTPException(status_code=404, detail="Doctor not found")
    try:
        target = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")
    rows = (await db.execute(
        select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.day_of_week == target.weekday(),
        )
    )).scalars().all()
    times = sorted({r.time_slot for r in rows})
    if not times:
        return []
    day_start = datetime.combine(target, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    busy_query = select(Appointment.slot_datetime).where(
        Appointment.status.in_(("scheduled", "pending")),
        Appointment.slot_datetime >= day_start,
        Appointment.slot_datetime < day_end,
    )
    if doctor.clinic_id is not None:
        busy_query = busy_query.where(Appointment.clinic_id == doctor.clinic_id)
    busy_rows = (await db.execute(busy_query)).scalars().all()
    # busy_rows are naive UTC; doctor schedule time_slot is MSK (HH:MM).
    busy_times = {(dt + MSK_OFFSET).strftime("%H:%M") for dt in busy_rows}
    return [DoctorSlot(time=t, busy=t in busy_times) for t in times]

@app.get("/api/slots", response_model=List[SlotSchema])
async def get_slots(clinic_id: int, service_id: int, date: str, db: AsyncSession = Depends(get_db)):
    clinic = (await db.execute(select(Clinic).where(Clinic.id == clinic_id))).scalar_one_or_none()
    service = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if not clinic or not service:
        raise HTTPException(status_code=404, detail="Clinic or Service not found")
    date_dt = datetime.strptime(date, "%Y-%m-%d")
    slots = await mis_provider.get_slots(
        clinic.mis_external_id or str(clinic.id),
        service.mis_external_id or str(service.id),
        date_dt,
        date_dt + timedelta(days=1),
    )
    return slots


@app.post("/api/appointments", response_model=AppointmentSchema)
async def create_appointment(
    data: AppointmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info("create_appointment: user_id=%s data=%s", user.id, data.model_dump())
    if not user.consent_timestamp:
        raise HTTPException(status_code=403, detail="Consent required")

    clinic = (await db.execute(select(Clinic).where(Clinic.id == data.clinic_id))).scalar_one_or_none()
    service = (await db.execute(select(Service).where(Service.id == data.service_id))).scalar_one_or_none()
    if not clinic or not service:
        raise HTTPException(status_code=404, detail="Clinic or Service not found")

    child_id = data.child_id
    if child_id is None:
        prof = (await db.execute(
            select(ParentProfile).where(ParentProfile.user_id == user.id).options(selectinload(ParentProfile.children))
        )).scalar_one_or_none()
        if prof and prof.children:
            child_id = prof.children[0].id

    if child_id is None:
        raise HTTPException(status_code=400, detail="Child profile is required")

    slot_dt_naive = data.slot_datetime.replace(tzinfo=None) if data.slot_datetime.tzinfo else data.slot_datetime
    conflict = (await db.execute(
        select(Appointment.id).where(
            Appointment.clinic_id == data.clinic_id,
            Appointment.slot_datetime == slot_dt_naive,
            Appointment.status.in_(("scheduled", "pending")),
        )
    )).scalar_one_or_none()
    if conflict is not None:
        raise HTTPException(status_code=409, detail="Этот слот уже занят, выберите другое время")

    try:
        mis_id = await mis_provider.create_appointment({
            "clinic_id": clinic.mis_external_id or str(clinic.id),
            "service_id": service.mis_external_id or str(service.id),
            "datetime": data.slot_datetime,
            "user_id": user.telegram_id,
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    appointment = Appointment(
        user_id=user.id, clinic_id=data.clinic_id, service_id=data.service_id,
        child_id=child_id, slot_datetime=data.slot_datetime, mis_external_id=mis_id, comment=data.comment,
        status="pending",
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    # Notify clinic admins
    parent = (await db.execute(select(ParentProfile).where(ParentProfile.user_id == user.id))).scalar_one_or_none()
    child = (await db.execute(select(ChildProfile).where(ChildProfile.id == child_id))).scalar_one_or_none()
    title = f"Новая запись: {service.name}"
    body_parts = [f"Пациент: {child.fio if child else '—'}"]
    if parent:
        body_parts.append(f"Родитель: {parent.fio} ({parent.phone})")
    body_parts.append(f"Время: {_fmt_msk(appointment.slot_datetime)}")
    if data.comment:
        body_parts.append(f"Комментарий: {data.comment}")
    db.add(AdminNotification(
        clinic_id=data.clinic_id,
        type="appointment_created",
        title=title,
        body="\n".join(body_parts),
        appointment_id=appointment.id,
    ))
    await db.commit()
    return appointment


@app.get("/api/appointments", response_model=List[AppointmentDetail])
async def get_my_appointments(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            Appointment.id, Appointment.service_id, Appointment.clinic_id,
            Appointment.slot_datetime, Appointment.status, Appointment.comment, Appointment.created_at,
            Service.name.label("service_name"), Clinic.name.label("clinic_name"),
        )
        .join(Service, Appointment.service_id == Service.id)
        .join(Clinic, Appointment.clinic_id == Clinic.id)
        .where(Appointment.user_id == user.id)
        .order_by(Appointment.slot_datetime.desc())
    )
    return [
        AppointmentDetail(
            id=row.id, service_id=row.service_id, clinic_id=row.clinic_id,
            service_name=row.service_name, clinic_name=row.clinic_name,
            slot_datetime=row.slot_datetime, status=row.status,
            comment=row.comment, created_at=row.created_at,
        )
        for row in result.all()
    ]


@app.patch("/api/appointments/{appointment_id}/reschedule", response_model=AppointmentSchema)
async def reschedule_appointment(
    appointment_id: int, data: AppointmentReschedule,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    appointment = (await db.execute(
        select(Appointment).where(Appointment.id == appointment_id, Appointment.user_id == user.id)
    )).scalar_one_or_none()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.status != "scheduled":
        raise HTTPException(status_code=400, detail="Appointment already cancelled or completed")
    new_slot = data.slot_datetime.replace(tzinfo=None) if data.slot_datetime.tzinfo else data.slot_datetime
    if new_slot.replace(tzinfo=timezone.utc) <= datetime.now(tz=timezone.utc):
        raise HTTPException(status_code=400, detail="New slot must be in the future")
    conflict = (await db.execute(
        select(Appointment.id).where(
            Appointment.clinic_id == appointment.clinic_id,
            Appointment.slot_datetime == new_slot,
            Appointment.status.in_(("scheduled", "pending")),
            Appointment.id != appointment.id,
        )
    )).scalar_one_or_none()
    if conflict is not None:
        raise HTTPException(status_code=409, detail="Этот слот уже занят, выберите другое время")
    try:
        await mis_provider.reschedule_appointment(appointment.mis_external_id, new_slot)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    appointment.slot_datetime = new_slot
    await db.commit()
    await db.refresh(appointment)
    return appointment


@app.delete("/api/appointments/{appointment_id}")
async def cancel_appointment(
    appointment_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    appointment = (await db.execute(
        select(Appointment).where(Appointment.id == appointment_id, Appointment.user_id == user.id)
    )).scalar_one_or_none()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.status not in ("scheduled", "pending"):
        raise HTTPException(status_code=400, detail="Appointment already cancelled or completed")
    slot_dt = appointment.slot_datetime.replace(tzinfo=timezone.utc)
    if slot_dt - datetime.now(tz=timezone.utc) < timedelta(hours=24):
        raise HTTPException(status_code=400, detail="Отмена возможна не позднее чем за 24 часа до визита")
    try:
        await mis_provider.cancel_appointment(appointment.mis_external_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    appointment.status = "cancelled"

    # Notify clinic admins about cancellation
    service = (await db.execute(select(Service).where(Service.id == appointment.service_id))).scalar_one_or_none()
    parent = (await db.execute(select(ParentProfile).where(ParentProfile.user_id == user.id))).scalar_one_or_none()
    db.add(AdminNotification(
        clinic_id=appointment.clinic_id,
        type="appointment_cancelled",
        title=f"Отмена записи: {service.name if service else ''}",
        body=(
            f"Пациент: {(parent.fio if parent else '—')}\n"
            f"Время: {_fmt_msk(appointment.slot_datetime)}"
        ),
        appointment_id=appointment.id,
    ))
    await db.commit()
    return {"status": "ok"}


@app.post("/api/support", response_model=SupportTicketSchema)
async def create_ticket(data: SupportTicketCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ticket = SupportTicket(user_id=user.id, message=data.message)
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)
    return ticket


@app.post("/api/consent")
async def accept_consent(version: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    already_consented = user.consent_timestamp is not None
    user.consent_version = version
    user.consent_timestamp = datetime.utcnow()
    await db.commit()
    if not already_consented and user.telegram_id != 12345678:
        try:
            from aiogram import Bot as TgBot
            tg_bot = TgBot(token=settings.BOT_TOKEN)
            await tg_bot.send_message(
                user.telegram_id,
                "✅ Вы дали согласие на обработку персональных данных.\n\n"
                "Теперь вам доступен полный функционал сервиса «Иду к врачу»! 🏥",
                reply_markup=_get_main_kb_for_notify(user.telegram_id),
            )
            await tg_bot.session.close()
        except Exception:
            logger.warning("consent: не удалось отправить уведомление telegram_id=%s", user.telegram_id, exc_info=True)
    return {"status": "ok"}


@app.get("/api/profile", response_model=ProfileResponse)
async def get_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profile = (await db.execute(
        select(ParentProfile).where(ParentProfile.user_id == user.id).options(selectinload(ParentProfile.children))
    )).scalar_one_or_none()
    if not profile:
        return ProfileResponse()
    child = profile.children[0] if profile.children else None
    return ProfileResponse(
        parent_fio=profile.fio, phone=profile.phone,
        child_fio=child.fio if child else None,
        child_birth_date=child.birth_date if child else None,
        child_id=child.id if child else None,
    )


@app.put("/api/profile")
async def save_profile(data: ProfileSaveRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    profile = (await db.execute(
        select(ParentProfile).where(ParentProfile.user_id == user.id).options(selectinload(ParentProfile.children))
    )).scalar_one_or_none()
    if not profile:
        profile = ParentProfile(user_id=user.id, fio=data.parent_fio, phone=data.phone)
        db.add(profile)
        await db.flush()
        db.add(ChildProfile(parent_id=profile.id, fio=data.child_fio, birth_date=data.child_birth_date))
        await db.flush()
    else:
        profile.fio = data.parent_fio
        profile.phone = data.phone
        if profile.children:
            profile.children[0].fio = data.child_fio
            profile.children[0].birth_date = data.child_birth_date
        else:
            db.add(ChildProfile(parent_id=profile.id, fio=data.child_fio, birth_date=data.child_birth_date))
            await db.flush()
    await db.commit()
    refetch = (await db.execute(
        select(ParentProfile).where(ParentProfile.user_id == user.id).options(selectinload(ParentProfile.children))
    )).scalar_one()
    child_id = refetch.children[0].id if refetch.children else None
    return {"status": "ok", "child_id": child_id}


def _get_main_kb_for_notify(tg_id, path: str = "", text: str = "🏥 Открыть приложение"):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    url = settings.WEB_APP_URL.rstrip("/") + path
    btn = (
        InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))
        if settings.WEB_APP_URL.startswith("https://")
        else InlineKeyboardButton(text=text, url=url)
    )
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])


@app.post("/api/progress")
async def update_progress(item_id: int, status: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    prog = (await db.execute(select(Progress).where(Progress.item_id == item_id, Progress.user_id == user.id))).scalar_one_or_none()
    if not prog:
        prog = Progress(user_id=user.id, item_id=item_id, status=status)
        db.add(prog)
    else:
        prog.status = status
        prog.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "ok"}


@app.get("/api/public/materials", response_model=List[dict])
async def get_public_materials(db: AsyncSession = Depends(get_db)):
    """Active materials added via admin panel, for the bot WebApp landing page.

    Public (no auth) — used by frontend/index.html to append admin-managed
    cards (Мультфильм / Игра-тренажёр) alongside the static ones.
    """
    rows = (await db.execute(
        select(ContentModule, Direction.name)
        .join(Direction, ContentModule.direction_id == Direction.id)
        .where(ContentModule.is_active == True)
        .order_by(ContentModule.id)
    )).all()
    return [
        {
            "id": m.id,
            "direction_name": direction_name,
            "content_type": m.content_type or "",
            "title": m.title,
            "description": m.description or "",
            "duration_minutes": m.duration_minutes,
            "url": m.url or "",
        }
        for m, direction_name in rows
    ]


@app.get("/api/modules", response_model=List[dict])
async def get_modules(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    modules = (await db.execute(select(ContentModule).options(joinedload(ContentModule.items)))).scalars().unique().all()
    purchased = [p.module_id for p in (await db.execute(
        select(Purchase).where(Purchase.user_id == user.id, Purchase.status == "completed")
    )).scalars().all()]
    return [
        {"id": m.id, "title": m.title, "description": m.description, "is_free": m.is_free,
         "price_stars": m.price_stars, "is_available": m.is_free or m.id in purchased, "items_count": len(m.items)}
        for m in modules
    ]


@app.get("/api/modules/{module_id}/items")
async def get_module_items(module_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    module = (await db.execute(select(ContentModule).where(ContentModule.id == module_id))).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    if not module.is_free:
        if not (await db.execute(
            select(Purchase).where(Purchase.user_id == user.id, Purchase.module_id == module_id, Purchase.status == "completed")
        )).scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Module not purchased")
    result = await db.execute(
        select(ContentItem, Progress.status)
        .outerjoin(Progress, (Progress.item_id == ContentItem.id) & (Progress.user_id == user.id))
        .where(ContentItem.module_id == module_id)
        .order_by(ContentItem.order)
    )
    return [{"id": i.id, "type": i.type, "title": i.title, "url": i.url, "status": s or "not_started"}
            for i, s in result.all()]


@app.post("/api/purchases")
async def create_purchase(module_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if (await db.execute(select(Purchase).where(Purchase.user_id == user.id, Purchase.module_id == module_id, Purchase.status == "completed"))).scalar_one_or_none():
        return {"status": "already_purchased"}
    module = (await db.execute(select(ContentModule).where(ContentModule.id == module_id))).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    purchase = Purchase(user_id=user.id, module_id=module_id, status="pending")
    db.add(purchase)
    await db.commit()
    await db.refresh(purchase)
    if settings.DEBUG:
        purchase.status = "completed"
        await db.commit()
        return {"status": "success", "purchase_id": purchase.id}
    return {"status": "pending", "purchase_id": purchase.id}


@app.post("/api/payments/webhook")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    return {"status": "ok"}


# ── Legacy admin HTML routes ──────────────────────────────────

@app.get("/admin/tickets", response_class=HTMLResponse)
async def admin_tickets(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SupportTicket).options(joinedload(SupportTicket.user)).order_by(SupportTicket.created_at.desc())
    )
    tickets = result.scalars().all()
    return templates.TemplateResponse("admin/tickets.html", {"request": request, "tickets": tickets, "active_page": "tickets"})


@app.post("/admin/tickets/{ticket_id}/close")
async def close_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    ticket = (await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))).scalar_one_or_none()
    if ticket:
        ticket.status = "closed"
        await db.commit()
    return RedirectResponse(url="/admin/tickets", status_code=303)


# ── Admin API: auth ───────────────────────────────────────────

@app.post("/admin/api/login")
async def admin_login(data: AdminLoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(
        select(AdminUser).where(AdminUser.username == data.username)
    )).scalar_one_or_none()
    if not user or not user.is_active or user.password_hash != _hash_pw(data.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "token": _make_admin_token(user.id),
        "username": user.username,
        "is_superadmin": user.is_superadmin,
        "clinic_id": user.clinic_id,
    }


@app.get("/admin/api/me", response_model=AdminMe)
async def admin_me(admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    clinic_name = None
    if admin.clinic_id is not None:
        clinic = (await db.execute(select(Clinic).where(Clinic.id == admin.clinic_id))).scalar_one_or_none()
        clinic_name = clinic.name if clinic else None
    return AdminMe(
        id=admin.id, username=admin.username, full_name=admin.full_name,
        is_superadmin=admin.is_superadmin, clinic_id=admin.clinic_id,
        clinic_name=clinic_name,
    )


# ── Admin API: stats ──────────────────────────────────────────

@app.get("/admin/api/stats", response_model=AdminStats)
async def admin_stats(admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    is_super = admin.is_superadmin
    cid = admin.clinic_id

    services_q = select(func.count()).select_from(Service)
    directions_q = select(func.count()).select_from(Direction)
    clinics_q = select(func.count()).select_from(Clinic)
    doctors_q = select(func.count()).select_from(Doctor)
    content_q = select(func.count()).select_from(ContentModule)
    appts_q = select(func.count()).select_from(Appointment)
    users_q = select(func.count()).select_from(User)
    cities_q = select(func.count()).select_from(City).where(City.is_active == True)

    if not is_super:
        if cid is None:
            raise HTTPException(status_code=403, detail="Admin has no clinic assigned")
        clinic_direction_ids = select(Direction.id).where(Direction.clinic_id == cid)
        services_q = services_q.where(Service.direction_id.in_(clinic_direction_ids))
        directions_q = directions_q.where(Direction.clinic_id == cid)
        clinics_q = clinics_q.where(Clinic.id == cid)
        doctors_q = doctors_q.where(Doctor.clinic_id == cid)
        appts_q = appts_q.where(Appointment.clinic_id == cid)
        # content scoped to clinic's directions
        content_q = content_q.where(ContentModule.direction_id.in_(clinic_direction_ids))
        # users who booked into this clinic
        users_q = select(func.count(func.distinct(Appointment.user_id))).select_from(Appointment).where(Appointment.clinic_id == cid)
        # cities: only clinic's city
        cities_q = select(func.count()).select_from(City).where(
            City.id == select(Clinic.city_id).where(Clinic.id == cid).scalar_subquery()
        )

    counts = await asyncio.gather(
        db.scalar(services_q),
        db.scalar(cities_q),
        db.scalar(clinics_q),
        db.scalar(doctors_q),
        db.scalar(content_q),
        db.scalar(users_q),
        db.scalar(appts_q),
        db.scalar(directions_q),
    )
    return AdminStats(
        services_count=counts[0] or 0, cities_count=counts[1] or 0,
        clinics_count=counts[2] or 0, doctors_count=counts[3] or 0,
        content_count=counts[4] or 0, users_count=counts[5] or 0,
        appointments_count=counts[6] or 0,
        directions_count=counts[7] or 0,
    )


# ── Admin API: directions ─────────────────────────────────────

async def _direction_to_item(d: Direction, db: AsyncSession) -> AdminDirectionItem:
    clinic = (await db.execute(select(Clinic).where(Clinic.id == d.clinic_id))).scalar_one_or_none()
    services_count = (await db.scalar(
        select(func.count()).select_from(Service).where(Service.direction_id == d.id)
    )) or 0
    content_count = (await db.scalar(
        select(func.count()).select_from(ContentModule).where(ContentModule.direction_id == d.id)
    )) or 0
    return AdminDirectionItem(
        id=d.id, clinic_id=d.clinic_id, clinic_name=clinic.name if clinic else "",
        name=d.name, desc=d.description or "", icon=d.icon or "", color=d.color or "#128395",
        active=d.is_active, services_count=services_count, content_count=content_count,
    )


@app.get("/admin/api/directions", response_model=List[AdminDirectionItem])
async def admin_list_directions(admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    stmt = select(Direction)
    if not admin.is_superadmin:
        if admin.clinic_id is None:
            return []
        stmt = stmt.where(Direction.clinic_id == admin.clinic_id)
    rows = (await db.execute(stmt.order_by(Direction.id))).scalars().all()
    return [await _direction_to_item(d, db) for d in rows]


@app.post("/admin/api/directions", response_model=AdminDirectionItem, status_code=201)
async def admin_create_direction(
    data: AdminDirectionCreate,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    target_clinic = data.clinic_id if admin.is_superadmin else admin.clinic_id
    if target_clinic is None:
        raise HTTPException(status_code=400, detail="clinic_id is required")
    _ensure_clinic_access(admin, target_clinic)
    target_clinics = {target_clinic}
    if admin.is_superadmin and data.also_in_clinic_ids:
        target_clinics.update(int(c) for c in data.also_in_clinic_ids)
    valid_ids = set((await db.execute(
        select(Clinic.id).where(Clinic.id.in_(target_clinics))
    )).scalars().all())
    if target_clinic not in valid_ids:
        raise HTTPException(status_code=404, detail="Clinic not found")
    created: List[Direction] = []
    for cid in sorted(valid_ids):
        d = Direction(
            clinic_id=cid, name=data.name, description=data.desc,
            icon=data.icon, color=data.color, is_active=data.active,
        )
        db.add(d)
        created.append(d)
    await db.commit()
    primary = next((d for d in created if d.clinic_id == target_clinic), created[0])
    await db.refresh(primary)
    return await _direction_to_item(primary, db)


@app.put("/admin/api/directions/{direction_id}", response_model=AdminDirectionItem)
async def admin_update_direction(
    direction_id: int,
    data: AdminDirectionUpdate,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    direction = (await db.execute(select(Direction).where(Direction.id == direction_id))).scalar_one_or_none()
    if not direction:
        raise HTTPException(status_code=404, detail="Direction not found")
    _ensure_clinic_access(admin, direction.clinic_id)
    direction.name = data.name
    direction.description = data.desc
    direction.icon = data.icon
    direction.color = data.color
    direction.is_active = data.active
    await db.commit()
    await db.refresh(direction)
    return await _direction_to_item(direction, db)


@app.delete("/admin/api/directions/{direction_id}")
async def admin_delete_direction(
    direction_id: int,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    direction = (await db.execute(select(Direction).where(Direction.id == direction_id))).scalar_one_or_none()
    if not direction:
        raise HTTPException(status_code=404, detail="Direction not found")
    _ensure_clinic_access(admin, direction.clinic_id)
    await db.delete(direction)
    await db.commit()
    return {"status": "ok"}


# ── Admin API: services ───────────────────────────────────────

async def _service_to_item(svc: Service, db: AsyncSession) -> AdminServiceItem:
    direction = (await db.execute(select(Direction).where(Direction.id == svc.direction_id))).scalar_one_or_none()
    clinic_id = direction.clinic_id if direction else 0
    clinic = (await db.execute(select(Clinic).where(Clinic.id == clinic_id))).scalar_one_or_none() if clinic_id else None
    return AdminServiceItem(
        id=svc.id, direction_id=svc.direction_id,
        direction_name=direction.name if direction else "",
        clinic_id=clinic_id, clinic_name=clinic.name if clinic else "",
        name=svc.name, desc=svc.description or "", icon=svc.icon or "", active=svc.is_active,
    )


async def _resolve_direction_for_clinic(name: str, clinic_id: int, db: AsyncSession) -> Direction:
    """Find an existing direction with the same name in clinic_id, or create one."""
    existing = (await db.execute(
        select(Direction).where(Direction.clinic_id == clinic_id, Direction.name == name)
    )).scalar_one_or_none()
    if existing:
        return existing
    new_dir = Direction(clinic_id=clinic_id, name=name, description="", icon="", color="#128395", is_active=True)
    db.add(new_dir)
    await db.flush()
    return new_dir


@app.get("/admin/api/services", response_model=List[AdminServiceItem])
async def admin_list_services(admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    stmt = select(Service).join(Direction, Service.direction_id == Direction.id)
    if not admin.is_superadmin:
        if admin.clinic_id is None:
            return []
        stmt = stmt.where(Direction.clinic_id == admin.clinic_id)
    rows = (await db.execute(stmt.order_by(Service.id))).scalars().all()
    return [await _service_to_item(s, db) for s in rows]


@app.post("/admin/api/services", response_model=AdminServiceItem, status_code=201)
async def admin_create_service(
    data: AdminServiceCreate,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    direction = (await db.execute(select(Direction).where(Direction.id == data.direction_id))).scalar_one_or_none()
    if not direction:
        raise HTTPException(status_code=404, detail="Direction not found")
    _ensure_clinic_access(admin, direction.clinic_id)
    primary_svc = Service(
        direction_id=direction.id,
        name=data.name,
        service_type=data.name.lower(),
        description=data.desc,
        icon=data.icon,
        is_active=data.active,
    )
    db.add(primary_svc)
    await db.flush()

    if admin.is_superadmin and data.also_in_clinic_ids:
        for cid in data.also_in_clinic_ids:
            if cid == direction.clinic_id:
                continue
            if not (await db.execute(select(Clinic.id).where(Clinic.id == cid))).scalar_one_or_none():
                continue
            target_dir = await _resolve_direction_for_clinic(direction.name, cid, db)
            if target_dir.icon is None or target_dir.icon == "":
                target_dir.icon = direction.icon
            db.add(Service(
                direction_id=target_dir.id, name=data.name, service_type=data.name.lower(),
                description=data.desc, icon=data.icon, is_active=data.active,
            ))

    await db.commit()
    await db.refresh(primary_svc)
    return await _service_to_item(primary_svc, db)


@app.put("/admin/api/services/{service_id}", response_model=AdminServiceItem)
async def admin_update_service(
    service_id: int,
    data: AdminServiceUpdate,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    current_dir = (await db.execute(select(Direction).where(Direction.id == svc.direction_id))).scalar_one_or_none()
    if not current_dir:
        raise HTTPException(status_code=500, detail="Service has no direction")
    _ensure_clinic_access(admin, current_dir.clinic_id)
    if data.direction_id is not None and data.direction_id != svc.direction_id:
        new_dir = (await db.execute(select(Direction).where(Direction.id == data.direction_id))).scalar_one_or_none()
        if not new_dir:
            raise HTTPException(status_code=404, detail="Target direction not found")
        _ensure_clinic_access(admin, new_dir.clinic_id)
        if not admin.is_superadmin and new_dir.clinic_id != current_dir.clinic_id:
            raise HTTPException(status_code=403, detail="Cannot move service to another clinic")
        svc.direction_id = new_dir.id
    svc.name = data.name
    svc.description = data.desc
    svc.icon = data.icon
    svc.is_active = data.active
    await db.commit()
    await db.refresh(svc)
    return await _service_to_item(svc, db)


@app.delete("/admin/api/services/{service_id}")
async def admin_delete_service(
    service_id: int,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    svc = (await db.execute(select(Service).where(Service.id == service_id))).scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    direction = (await db.execute(select(Direction).where(Direction.id == svc.direction_id))).scalar_one_or_none()
    clinic_id = direction.clinic_id if direction else None
    _ensure_clinic_access(admin, clinic_id)
    await db.delete(svc)
    await db.commit()
    return {"status": "ok"}


# ── Admin API: cities ─────────────────────────────────────────

def _city_to_item(c: City, clinics_count: int) -> AdminCityItem:
    return AdminCityItem(id=c.id, name=c.name, region=c.region or "", active=c.is_active, clinicsCount=clinics_count)


@app.get("/admin/api/cities", response_model=List[AdminCityItem])
async def admin_list_cities(admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    # Read-only for everyone (used to populate dropdowns); writes are super-only.
    cities = (await db.execute(select(City))).scalars().all()
    result = []
    for c in cities:
        cnt = (await db.scalar(select(func.count()).select_from(Clinic).where(Clinic.city_id == c.id))) or 0
        result.append(_city_to_item(c, cnt))
    return result


@app.post("/admin/api/cities", response_model=AdminCityItem, status_code=201)
async def admin_create_city(data: AdminCityCreate, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    city = City(name=data.name, region=data.region, is_active=data.active)
    db.add(city)
    await db.commit()
    await db.refresh(city)
    return _city_to_item(city, 0)


@app.put("/admin/api/cities/{city_id}", response_model=AdminCityItem)
async def admin_update_city(city_id: int, data: AdminCityUpdate, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    city = (await db.execute(select(City).where(City.id == city_id))).scalar_one_or_none()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    city.name = data.name
    city.region = data.region
    city.is_active = data.active
    await db.commit()
    cnt = (await db.scalar(select(func.count()).select_from(Clinic).where(Clinic.city_id == city_id))) or 0
    return _city_to_item(city, cnt)


@app.delete("/admin/api/cities/{city_id}")
async def admin_delete_city(city_id: int, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    city = (await db.execute(select(City).where(City.id == city_id))).scalar_one_or_none()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    await db.delete(city)
    await db.commit()
    return {"status": "ok"}


# ── Admin API: clinics ────────────────────────────────────────

async def _clinic_to_item(clinic: Clinic, db: AsyncSession) -> AdminClinicItem:
    city = (await db.execute(select(City).where(City.id == clinic.city_id))).scalar_one_or_none()
    city_name = city.name if city else ""
    svcs = (await db.execute(
        select(Service).join(Direction, Service.direction_id == Direction.id)
        .where(Direction.clinic_id == clinic.id)
    )).scalars().all()
    directions_count = (await db.scalar(
        select(func.count()).select_from(Direction).where(Direction.clinic_id == clinic.id)
    )) or 0
    return AdminClinicItem(
        id=clinic.id, name=clinic.name, city=city_name, city_id=clinic.city_id,
        addr=clinic.address or "", phone=clinic.phone or "",
        services=[s.name for s in svcs], service_ids=[s.id for s in svcs],
        directions_count=directions_count,
        worktime=clinic.worktime or "", active=clinic.is_active,
    )


@app.get("/admin/api/clinics", response_model=List[AdminClinicItem])
async def admin_list_clinics(admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    stmt = select(Clinic)
    if not admin.is_superadmin:
        if admin.clinic_id is None:
            return []
        stmt = stmt.where(Clinic.id == admin.clinic_id)
    clinics = (await db.execute(stmt)).scalars().all()
    return [await _clinic_to_item(c, db) for c in clinics]


@app.post("/admin/api/clinics", response_model=AdminClinicItem, status_code=201)
async def admin_create_clinic(data: AdminClinicCreate, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    clinic = Clinic(
        city_id=data.city_id, name=data.name, address=data.addr,
        phone=data.phone, worktime=data.worktime, is_active=data.active,
    )
    db.add(clinic)
    await db.commit()
    await db.refresh(clinic)
    return await _clinic_to_item(clinic, db)


@app.put("/admin/api/clinics/{clinic_id}", response_model=AdminClinicItem)
async def admin_update_clinic(clinic_id: int, data: AdminClinicUpdate, admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    clinic = (await db.execute(select(Clinic).where(Clinic.id == clinic_id))).scalar_one_or_none()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")
    _ensure_clinic_access(admin, clinic_id)
    # Clinic admins can't reassign their clinic to a different city
    if not admin.is_superadmin and data.city_id != clinic.city_id:
        raise HTTPException(status_code=403, detail="Only superadmin can change city")
    clinic.city_id = data.city_id
    clinic.name = data.name
    clinic.address = data.addr
    clinic.phone = data.phone
    clinic.worktime = data.worktime
    clinic.is_active = data.active
    await db.commit()
    return await _clinic_to_item(clinic, db)


@app.delete("/admin/api/clinics/{clinic_id}")
async def admin_delete_clinic(clinic_id: int, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    clinic = (await db.execute(select(Clinic).where(Clinic.id == clinic_id))).scalar_one_or_none()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found")
    await db.delete(clinic)
    await db.commit()
    return {"status": "ok"}


# ── Admin API: doctors ────────────────────────────────────────

async def _doctor_to_item(doctor: Doctor, db: AsyncSession) -> AdminDoctorItem:
    clinic_name = ""
    if doctor.clinic_id:
        clinic = (await db.execute(select(Clinic).where(Clinic.id == doctor.clinic_id))).scalar_one_or_none()
        clinic_name = clinic.name if clinic else ""
    return AdminDoctorItem(
        id=doctor.id, name=doctor.name, spec=doctor.spec or "",
        clinic=clinic_name, clinic_id=doctor.clinic_id,
        exp=doctor.exp_years, minAge=doctor.min_age,
        color=doctor.color or "#16a085", initials=doctor.initials or "",
        avatar=doctor.avatar,
        active=doctor.is_active,
    )


@app.get("/admin/api/doctors", response_model=List[AdminDoctorItem])
async def admin_list_doctors(admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    stmt = select(Doctor)
    if not admin.is_superadmin:
        if admin.clinic_id is None:
            return []
        stmt = stmt.where(Doctor.clinic_id == admin.clinic_id)
    doctors = (await db.execute(stmt)).scalars().all()
    return [await _doctor_to_item(d, db) for d in doctors]


@app.post("/admin/api/doctors", response_model=AdminDoctorItem, status_code=201)
async def admin_create_doctor(data: AdminDoctorCreate, admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    target_clinic = data.clinic_id if admin.is_superadmin else admin.clinic_id
    if target_clinic is None:
        raise HTTPException(status_code=400, detail="clinic_id is required")
    _ensure_clinic_access(admin, target_clinic)
    doctor = Doctor(
        name=data.name, spec=data.spec, clinic_id=target_clinic,
        exp_years=data.exp, min_age=data.minAge,
        color=data.color, initials=data.initials,
        avatar=data.avatar, is_active=data.active,
    )
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    return await _doctor_to_item(doctor, db)


@app.put("/admin/api/doctors/{doctor_id}", response_model=AdminDoctorItem)
async def admin_update_doctor(doctor_id: int, data: AdminDoctorUpdate, admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    doctor = (await db.execute(select(Doctor).where(Doctor.id == doctor_id))).scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    _ensure_clinic_access(admin, doctor.clinic_id)
    new_clinic = data.clinic_id if admin.is_superadmin else admin.clinic_id
    if new_clinic is None:
        raise HTTPException(status_code=400, detail="clinic_id is required")
    if not admin.is_superadmin and new_clinic != doctor.clinic_id:
        raise HTTPException(status_code=403, detail="Cannot move doctor to another clinic")
    doctor.name = data.name
    doctor.spec = data.spec
    doctor.clinic_id = new_clinic
    doctor.exp_years = data.exp
    doctor.min_age = data.minAge
    doctor.color = data.color
    doctor.initials = data.initials
    doctor.avatar = data.avatar
    doctor.is_active = data.active
    await db.commit()
    return await _doctor_to_item(doctor, db)


@app.delete("/admin/api/doctors/{doctor_id}")
async def admin_delete_doctor(doctor_id: int, admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    doctor = (await db.execute(select(Doctor).where(Doctor.id == doctor_id))).scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    _ensure_clinic_access(admin, doctor.clinic_id)
    await db.delete(doctor)
    await db.commit()
    return {"status": "ok"}


@app.get("/admin/api/doctors/{doctor_id}/schedule")
async def admin_get_schedule(doctor_id: int, admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    doctor = (await db.execute(select(Doctor).where(Doctor.id == doctor_id))).scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    _ensure_clinic_access(admin, doctor.clinic_id)
    slots_rows = (await db.execute(select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id))).scalars().all()
    slots: Dict[str, Dict[str, bool]] = {str(i): {} for i in range(7)}
    for row in slots_rows:
        slots[str(row.day_of_week)][row.time_slot] = True
    return {"slots": slots}


@app.put("/admin/api/doctors/{doctor_id}/schedule")
async def admin_update_schedule(doctor_id: int, data: AdminScheduleUpdate, admin: AdminUser = Depends(get_admin), db: AsyncSession = Depends(get_db)):
    doctor = (await db.execute(select(Doctor).where(Doctor.id == doctor_id))).scalar_one_or_none()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")
    _ensure_clinic_access(admin, doctor.clinic_id)
    # Delete all existing slots
    existing = (await db.execute(select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id))).scalars().all()
    for row in existing:
        await db.delete(row)
    await db.flush()
    # Insert enabled slots
    for day_str, times in data.slots.items():
        for time_slot, enabled in times.items():
            if enabled:
                db.add(DoctorSchedule(doctor_id=doctor_id, day_of_week=int(day_str), time_slot=time_slot))
    await db.commit()
    return {"status": "ok"}


# ── Admin API: content (super-only — clinic admins do not access materials) ──

async def _content_to_item(m: ContentModule, db: AsyncSession) -> AdminContentItem:
    direction_name = ""
    clinic_id: Optional[int] = None
    clinic_name = ""
    if m.direction_id is not None:
        direction = (await db.execute(select(Direction).where(Direction.id == m.direction_id))).scalar_one_or_none()
        if direction:
            direction_name = direction.name
            clinic_id = direction.clinic_id
            clinic = (await db.execute(select(Clinic).where(Clinic.id == direction.clinic_id))).scalar_one_or_none()
            clinic_name = clinic.name if clinic else ""
    return AdminContentItem(
        id=m.id, direction_id=m.direction_id, direction_name=direction_name,
        clinic_id=clinic_id, clinic_name=clinic_name,
        type=m.content_type or "Мультфильм", title=m.title,
        desc=m.description or "", duration=m.duration_minutes,
        url=m.url or "", active=m.is_active,
    )


@app.get("/admin/api/content", response_model=List[AdminContentItem])
async def admin_list_content(admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    modules = (await db.execute(select(ContentModule).order_by(ContentModule.id))).scalars().all()
    return [await _content_to_item(m, db) for m in modules]


@app.post("/admin/api/content", response_model=AdminContentItem, status_code=201)
async def admin_create_content(data: AdminContentCreate, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    if data.direction_id is None:
        raise HTTPException(status_code=400, detail="direction_id is required")
    direction = (await db.execute(select(Direction).where(Direction.id == data.direction_id))).scalar_one_or_none()
    if not direction:
        raise HTTPException(status_code=404, detail="Direction not found")
    primary = ContentModule(
        title=data.title, description=data.desc,
        direction_id=direction.id, content_type=data.type,
        duration_minutes=data.duration, url=data.url, is_active=data.active,
    )
    db.add(primary)
    await db.flush()

    if data.also_in_clinic_ids:
        for cid in data.also_in_clinic_ids:
            if cid == direction.clinic_id:
                continue
            if not (await db.execute(select(Clinic.id).where(Clinic.id == cid))).scalar_one_or_none():
                continue
            target_dir = await _resolve_direction_for_clinic(direction.name, cid, db)
            if target_dir.icon is None or target_dir.icon == "":
                target_dir.icon = direction.icon
            db.add(ContentModule(
                title=data.title, description=data.desc,
                direction_id=target_dir.id, content_type=data.type,
                duration_minutes=data.duration, url=data.url, is_active=data.active,
            ))

    await db.commit()
    await db.refresh(primary)
    return await _content_to_item(primary, db)


@app.put("/admin/api/content/{content_id}", response_model=AdminContentItem)
async def admin_update_content(content_id: int, data: AdminContentUpdate, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    module = (await db.execute(select(ContentModule).where(ContentModule.id == content_id))).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Content not found")
    if data.direction_id is not None and data.direction_id != module.direction_id:
        target = (await db.execute(select(Direction).where(Direction.id == data.direction_id))).scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="Target direction not found")
        module.direction_id = target.id
    module.title = data.title
    module.description = data.desc
    module.content_type = data.type
    module.duration_minutes = data.duration
    module.url = data.url
    module.is_active = data.active
    await db.commit()
    return await _content_to_item(module, db)


@app.delete("/admin/api/content/{content_id}")
async def admin_delete_content(content_id: int, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    module = (await db.execute(select(ContentModule).where(ContentModule.id == content_id))).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Content not found")
    await db.delete(module)
    await db.commit()
    return {"status": "ok"}


# ── Admin API: roles ──────────────────────────────────────────

def _role_to_item(r: AdminRole) -> AdminRoleItem:
    try:
        perms = json.loads(r.perms or "{}")
    except Exception:
        perms = {}
    return AdminRoleItem(id=r.id, name=r.name, desc=r.description or "", color=r.color or "#2980b9", perms=perms)


@app.get("/admin/api/roles", response_model=List[AdminRoleItem])
async def admin_list_roles(admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    roles = (await db.execute(select(AdminRole))).scalars().all()
    return [_role_to_item(r) for r in roles]


@app.post("/admin/api/roles", response_model=AdminRoleItem, status_code=201)
async def admin_create_role(data: AdminRoleCreate, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    role = AdminRole(name=data.name, description=data.desc, color=data.color, perms=json.dumps(data.perms))
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return _role_to_item(role)


@app.put("/admin/api/roles/{role_id}", response_model=AdminRoleItem)
async def admin_update_role(role_id: int, data: AdminRoleUpdate, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    role = (await db.execute(select(AdminRole).where(AdminRole.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    role.name = data.name
    role.description = data.desc
    role.color = data.color
    role.perms = json.dumps(data.perms)
    await db.commit()
    return _role_to_item(role)


@app.delete("/admin/api/roles/{role_id}")
async def admin_delete_role(role_id: int, admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    role = (await db.execute(select(AdminRole).where(AdminRole.id == role_id))).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    await db.delete(role)
    await db.commit()
    return {"status": "ok"}


# ── Admin API: admin users (super-only) ───────────────────────

async def _admin_user_to_item(u: AdminUser, db: AsyncSession) -> AdminUserItem:
    clinic_name = None
    if u.clinic_id is not None:
        clinic = (await db.execute(select(Clinic).where(Clinic.id == u.clinic_id))).scalar_one_or_none()
        clinic_name = clinic.name if clinic else None
    return AdminUserItem(
        id=u.id, username=u.username, full_name=u.full_name,
        is_superadmin=u.is_superadmin, clinic_id=u.clinic_id,
        clinic_name=clinic_name, is_active=u.is_active,
    )


@app.get("/admin/api/admin-users", response_model=List[AdminUserItem])
async def admin_list_admin_users(admin: AdminUser = Depends(require_super), db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(AdminUser).order_by(AdminUser.id))).scalars().all()
    return [await _admin_user_to_item(u, db) for u in users]


@app.post("/admin/api/admin-users", response_model=AdminUserItem, status_code=201)
async def admin_create_admin_user(
    data: AdminUserCreate,
    admin: AdminUser = Depends(require_super),
    db: AsyncSession = Depends(get_db),
):
    if (await db.execute(select(AdminUser.id).where(AdminUser.username == data.username))).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    if not data.is_superadmin and data.clinic_id is None:
        raise HTTPException(status_code=400, detail="clinic_id is required for clinic admins")
    if data.clinic_id is not None:
        if not (await db.execute(select(Clinic.id).where(Clinic.id == data.clinic_id))).scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Clinic not found")
    if not data.password:
        raise HTTPException(status_code=400, detail="Password is required")
    user = AdminUser(
        username=data.username,
        password_hash=_hash_pw(data.password),
        full_name=data.full_name or None,
        is_superadmin=data.is_superadmin,
        clinic_id=None if data.is_superadmin else data.clinic_id,
        is_active=data.is_active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await _admin_user_to_item(user, db)


@app.put("/admin/api/admin-users/{user_id}", response_model=AdminUserItem)
async def admin_update_admin_user(
    user_id: int,
    data: AdminUserUpdate,
    admin: AdminUser = Depends(require_super),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(AdminUser).where(AdminUser.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    if data.username != user.username:
        if (await db.execute(select(AdminUser.id).where(AdminUser.username == data.username))).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already exists")
    if not data.is_superadmin and data.clinic_id is None:
        raise HTTPException(status_code=400, detail="clinic_id is required for clinic admins")
    if data.clinic_id is not None:
        if not (await db.execute(select(Clinic.id).where(Clinic.id == data.clinic_id))).scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Clinic not found")
    user.username = data.username
    if data.password:
        user.password_hash = _hash_pw(data.password)
    user.full_name = data.full_name or None
    user.is_superadmin = data.is_superadmin
    user.clinic_id = None if data.is_superadmin else data.clinic_id
    user.is_active = data.is_active
    await db.commit()
    return await _admin_user_to_item(user, db)


@app.delete("/admin/api/admin-users/{user_id}")
async def admin_delete_admin_user(
    user_id: int,
    admin: AdminUser = Depends(require_super),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = (await db.execute(select(AdminUser).where(AdminUser.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    # Don't strand the system without any active superadmin
    if user.is_superadmin:
        remaining = (await db.scalar(
            select(func.count()).select_from(AdminUser).where(
                AdminUser.is_superadmin == True, AdminUser.is_active == True, AdminUser.id != user_id
            )
        )) or 0
        if remaining == 0:
            raise HTTPException(status_code=400, detail="Cannot delete the last superadmin")
    await db.delete(user)
    await db.commit()
    return {"status": "ok"}


# ── Admin API: notifications ──────────────────────────────────

def _scope_clinic_q(stmt, column, admin: AdminUser):
    if admin.is_superadmin:
        return stmt
    if admin.clinic_id is None:
        return stmt.where(False)
    return stmt.where(column == admin.clinic_id)


async def _notification_to_item(n: AdminNotification, db: AsyncSession) -> AdminNotificationItem:
    clinic = (await db.execute(select(Clinic).where(Clinic.id == n.clinic_id))).scalar_one_or_none()
    return AdminNotificationItem(
        id=n.id, clinic_id=n.clinic_id, clinic_name=clinic.name if clinic else "",
        type=n.type, title=n.title, body=n.body, appointment_id=n.appointment_id,
        is_read=n.is_read, created_at=n.created_at,
    )


@app.get("/admin/api/notifications", response_model=List[AdminNotificationItem])
async def admin_list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AdminNotification).order_by(AdminNotification.created_at.desc())
    stmt = _scope_clinic_q(stmt, AdminNotification.clinic_id, admin)
    if unread_only:
        stmt = stmt.where(AdminNotification.is_read == False)
    stmt = stmt.limit(max(1, min(limit, 200)))
    rows = (await db.execute(stmt)).scalars().all()
    return [await _notification_to_item(n, db) for n in rows]


@app.get("/admin/api/notifications/unread-count")
async def admin_notifications_unread_count(
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(func.count()).select_from(AdminNotification).where(AdminNotification.is_read == False)
    stmt = _scope_clinic_q(stmt, AdminNotification.clinic_id, admin)
    cnt = (await db.scalar(stmt)) or 0
    return {"count": int(cnt)}


@app.post("/admin/api/notifications/{notification_id}/read")
async def admin_mark_notification_read(
    notification_id: int,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    n = (await db.execute(select(AdminNotification).where(AdminNotification.id == notification_id))).scalar_one_or_none()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    _ensure_clinic_access(admin, n.clinic_id)
    n.is_read = True
    await db.commit()
    return {"status": "ok"}


@app.post("/admin/api/notifications/read-all")
async def admin_mark_all_notifications_read(
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AdminNotification).where(AdminNotification.is_read == False)
    stmt = _scope_clinic_q(stmt, AdminNotification.clinic_id, admin)
    rows = (await db.execute(stmt)).scalars().all()
    for n in rows:
        n.is_read = True
    await db.commit()
    return {"status": "ok", "updated": len(rows)}


# ── Admin API: appointments ───────────────────────────────────

async def _appointment_to_admin_item(a: Appointment, db: AsyncSession) -> AdminAppointmentItem:
    clinic = (await db.execute(select(Clinic).where(Clinic.id == a.clinic_id))).scalar_one_or_none()
    service = (await db.execute(select(Service).where(Service.id == a.service_id))).scalar_one_or_none()
    child = (await db.execute(select(ChildProfile).where(ChildProfile.id == a.child_id))).scalar_one_or_none() if a.child_id else None
    parent = (await db.execute(select(ParentProfile).where(ParentProfile.user_id == a.user_id))).scalar_one_or_none()
    tg_user = (await db.execute(select(User).where(User.id == a.user_id))).scalar_one_or_none()
    return AdminAppointmentItem(
        id=a.id, clinic_id=a.clinic_id, clinic_name=clinic.name if clinic else "",
        service_id=a.service_id, service_name=service.name if service else "",
        child_id=a.child_id, child_name=child.fio if child else "",
        parent_name=parent.fio if parent else "",
        parent_phone=parent.phone if parent else "",
        user_telegram_id=tg_user.telegram_id if tg_user else None,
        slot_datetime=a.slot_datetime, status=a.status,
        comment=a.comment, created_at=a.created_at,
    )


@app.get("/admin/api/appointments", response_model=List[AdminAppointmentItem])
async def admin_list_appointments(
    status: Optional[str] = None,
    limit: int = 100,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Appointment).order_by(Appointment.slot_datetime.desc())
    stmt = _scope_clinic_q(stmt, Appointment.clinic_id, admin)
    if status:
        stmt = stmt.where(Appointment.status == status)
    stmt = stmt.limit(max(1, min(limit, 500)))
    rows = (await db.execute(stmt)).scalars().all()
    return [await _appointment_to_admin_item(a, db) for a in rows]


async def _notify_user_appointment_confirmed(user: User, appointment: Appointment, db: AsyncSession) -> None:
    if user.telegram_id == 12345678:
        return  # debug stub user
    service = (await db.execute(select(Service).where(Service.id == appointment.service_id))).scalar_one_or_none()
    clinic = (await db.execute(select(Clinic).where(Clinic.id == appointment.clinic_id))).scalar_one_or_none()
    msg = (
        "✅ Ваша запись подтверждена!\n\n"
        f"Услуга: {service.name if service else ''}\n"
        f"Клиника: {clinic.name if clinic else ''}\n"
        f"Время: {_fmt_msk(appointment.slot_datetime)}"
    )
    try:
        from aiogram import Bot as TgBot
        tg_bot = TgBot(token=settings.BOT_TOKEN)
        await tg_bot.send_message(
            user.telegram_id,
            msg,
            reply_markup=_get_main_kb_for_notify(
                user.telegram_id,
                path="/booking.html?screen=appointments",
                text="📋 Мои записи",
            ),
        )
        await tg_bot.session.close()
    except Exception:
        logger.warning("confirm: не удалось отправить уведомление telegram_id=%s", user.telegram_id, exc_info=True)


@app.post("/admin/api/appointments/{appointment_id}/confirm", response_model=AdminAppointmentItem)
async def admin_confirm_appointment(
    appointment_id: int,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    appt = (await db.execute(select(Appointment).where(Appointment.id == appointment_id))).scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    _ensure_clinic_access(admin, appt.clinic_id)
    if appt.status == "scheduled":
        return await _appointment_to_admin_item(appt, db)
    if appt.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot confirm appointment in status '{appt.status}'")
    appt.status = "scheduled"
    await db.commit()

    user = (await db.execute(select(User).where(User.id == appt.user_id))).scalar_one_or_none()
    if user:
        await _notify_user_appointment_confirmed(user, appt, db)

    return await _appointment_to_admin_item(appt, db)


@app.post("/admin/api/appointments/{appointment_id}/cancel", response_model=AdminAppointmentItem)
async def admin_cancel_by_admin(
    appointment_id: int,
    admin: AdminUser = Depends(get_admin),
    db: AsyncSession = Depends(get_db),
):
    appt = (await db.execute(select(Appointment).where(Appointment.id == appointment_id))).scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    _ensure_clinic_access(admin, appt.clinic_id)
    if appt.status == "cancelled":
        return await _appointment_to_admin_item(appt, db)
    appt.status = "cancelled"
    await db.commit()
    return await _appointment_to_admin_item(appt, db)
