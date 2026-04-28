import asyncio
import logging
import time
from fastapi import FastAPI, Depends, HTTPException, Header, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from typing import List, Optional
import json
import os
from datetime import datetime, timedelta

from alembic import command
from alembic.config import Config

from .database import get_db, ensure_storage
from .seed import seed_if_empty
from .logging_utils import configure_logging, log_environment, log_settings
from .models import User, City, Clinic, Service, Appointment, SupportTicket, ContentModule, ContentItem, Purchase, Progress, ParentProfile, ChildProfile
from .schemas import (
    User as UserSchema,
    City as CitySchema,
    Clinic as ClinicSchema,
    Service as ServiceSchema,
    SlotSchema,
    AppointmentCreate,
    Appointment as AppointmentSchema,
    AppointmentDetail,
    SupportTicketCreate,
    SupportTicket as SupportTicketSchema,
    ProfileSaveRequest,
    ProfileResponse,
)
from .auth import validate_init_data
from .mis import mis_provider
from .config import settings

configure_logging()
logger = logging.getLogger("backend.api")

app = FastAPI(title="Иду к врачу API")


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
    logger.info(
        "<-- %s %s %s (%.1f ms)",
        request.method, request.url.path, response.status_code, duration_ms,
    )
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
    await seed_if_empty()
    logger.info("=== Backend готов к работе ===")

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(os.path.join(BASE_DIR, "frontend", "index.html"))

@app.get("/booking.html", include_in_schema=False)
async def booking():
    return FileResponse(os.path.join(BASE_DIR, "frontend", "booking.html"))

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
                logger.warning(
                    "auth: поле 'user' отсутствует в initData — подставлен debug telegram_id=%s (DEBUG=True)",
                    tg_id,
                )
            else:
                logger.warning("auth: поле 'user' отсутствует в initData — запрос отклонён")
                raise HTTPException(status_code=401, detail="User info missing")
        else:
            user_data = json.loads(user_json)
            tg_id = user_data.get("id")
            logger.info("auth: telegram_id=%s извлечён из подписанной initData", tg_id)
    except Exception:
        if settings.DEBUG:
            tg_id = 12345678
            logger.warning(
                "auth: ошибка парсинга initData — подставлен debug telegram_id=%s (DEBUG=True)",
                tg_id,
                exc_info=True,
            )
        else:
            logger.warning("auth: ошибка парсинга initData — запрос отклонён", exc_info=True)
            raise HTTPException(status_code=401, detail="Invalid user data")

    result = await db.execute(select(User).where(User.telegram_id == tg_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(telegram_id=tg_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("auth: создан новый User id=%s для telegram_id=%s", user.id, tg_id)

    return user

@app.get("/api/cities", response_model=List[CitySchema])
async def get_cities(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(City).where(City.is_active == True))
    return result.scalars().all()

@app.get("/api/clinics", response_model=List[ClinicSchema])
async def get_clinics(city_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Clinic).where(Clinic.city_id == city_id, Clinic.is_active == True))
    return result.scalars().all()

@app.get("/api/services", response_model=List[ServiceSchema])
async def get_services(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Service).where(Service.is_active == True))
    return result.scalars().all()

@app.get("/api/slots", response_model=List[SlotSchema])
async def get_slots(clinic_id: int, service_id: int, date: str, db: AsyncSession = Depends(get_db)):
    clinic_result = await db.execute(select(Clinic).where(Clinic.id == clinic_id))
    clinic = clinic_result.scalar_one_or_none()
    service_result = await db.execute(select(Service).where(Service.id == service_id))
    service = service_result.scalar_one_or_none()
    
    if not clinic or not service:
        raise HTTPException(status_code=404, detail="Clinic or Service not found")
        
    date_dt = datetime.strptime(date, "%Y-%m-%d")
    slots = await mis_provider.get_slots(
        clinic.mis_external_id or str(clinic.id),
        service.mis_external_id or str(service.id),
        date_dt,
        date_dt + timedelta(days=1)
    )
    return slots

@app.post("/api/appointments", response_model=AppointmentSchema)
async def create_appointment(
    data: AppointmentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    logger.info("create_appointment: user_id=%s data=%s", user.id, data.model_dump())

    if not user.consent_timestamp:
        logger.warning("create_appointment: отказ — нет consent_timestamp у user_id=%s", user.id)
        raise HTTPException(status_code=403, detail="Consent required")

    clinic_result = await db.execute(select(Clinic).where(Clinic.id == data.clinic_id))
    clinic = clinic_result.scalar_one_or_none()
    service_result = await db.execute(select(Service).where(Service.id == data.service_id))
    service = service_result.scalar_one_or_none()

    if not clinic or not service:
        logger.warning("create_appointment: clinic=%s service=%s не найдены", data.clinic_id, data.service_id)
        raise HTTPException(status_code=404, detail="Clinic or Service not found")

    child_id = data.child_id
    if child_id is None:
        prof_result = await db.execute(
            select(ParentProfile)
            .where(ParentProfile.user_id == user.id)
            .options(selectinload(ParentProfile.children))
        )
        profile = prof_result.scalar_one_or_none()
        if profile and profile.children:
            child_id = profile.children[0].id
            logger.info("create_appointment: child_id не передан, используем %s из профиля", child_id)

    if child_id is None:
        logger.warning("create_appointment: child_id отсутствует и не найден в профиле user_id=%s", user.id)
        raise HTTPException(status_code=400, detail="Child profile is required")

    try:
        mis_id = await mis_provider.create_appointment({
            "clinic_id": clinic.mis_external_id or str(clinic.id),
            "service_id": service.mis_external_id or str(service.id),
            "datetime": data.slot_datetime,
            "user_id": user.telegram_id
        })
    except Exception as e:
        logger.exception("create_appointment: MIS ошибка user_id=%s", user.id)
        raise HTTPException(status_code=400, detail=str(e))

    appointment = Appointment(
        user_id=user.id,
        clinic_id=data.clinic_id,
        service_id=data.service_id,
        child_id=child_id,
        slot_datetime=data.slot_datetime,
        mis_external_id=mis_id,
        comment=data.comment
    )
    db.add(appointment)
    try:
        await db.commit()
    except Exception:
        logger.exception("create_appointment: ошибка commit user_id=%s", user.id)
        raise HTTPException(status_code=500, detail="DB error")
    await db.refresh(appointment)
    logger.info("create_appointment: создана запись id=%s user_id=%s child_id=%s", appointment.id, user.id, child_id)
    return appointment

@app.get("/api/appointments", response_model=List[AppointmentDetail])
async def get_my_appointments(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Appointment)
        .where(Appointment.user_id == user.id)
        .options(selectinload(Appointment.clinic), selectinload(Appointment.service))
        .order_by(Appointment.slot_datetime.desc())
    )
    appointments = result.scalars().all()
    return [
        AppointmentDetail(
            id=a.id,
            service_name=a.service.name,
            clinic_name=a.clinic.name,
            slot_datetime=a.slot_datetime,
            status=a.status,
            comment=a.comment,
            created_at=a.created_at,
        )
        for a in appointments
    ]

@app.post("/api/support", response_model=SupportTicketSchema)
async def create_ticket(
    data: SupportTicketCreate, 
    user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
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

    if not already_consented:
        if user.telegram_id == 12345678:
            logger.warning("consent: пропускаем уведомление — debug-заглушка telegram_id=12345678 (initData был пустым)")
        else:
            try:
                from aiogram import Bot as TgBot
                tg_bot = TgBot(token=settings.BOT_TOKEN)
                await tg_bot.send_message(
                    user.telegram_id,
                    "✅ Вы дали согласие на обработку персональных данных.\n\n"
                    "Теперь вам доступен полный функционал сервиса «Иду к врачу»! 🏥\n"
                    "Нажмите кнопку ниже, чтобы открыть приложение.",
                    reply_markup=_get_main_kb_for_notify(),
                )
                await tg_bot.session.close()
                logger.info("consent: уведомление отправлено telegram_id=%s", user.telegram_id)
            except Exception:
                logger.warning(
                    "consent: не удалось отправить уведомление telegram_id=%s",
                    user.telegram_id,
                    exc_info=True,
                )

    return {"status": "ok"}


@app.get("/api/profile", response_model=ProfileResponse)
async def get_profile(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ParentProfile)
        .where(ParentProfile.user_id == user.id)
        .options(selectinload(ParentProfile.children))
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return ProfileResponse()
    child = profile.children[0] if profile.children else None
    return ProfileResponse(
        parent_fio=profile.fio,
        phone=profile.phone,
        child_fio=child.fio if child else None,
        child_birth_date=child.birth_date if child else None,
        child_id=child.id if child else None,
    )


@app.put("/api/profile")
async def save_profile(data: ProfileSaveRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ParentProfile)
        .where(ParentProfile.user_id == user.id)
        .options(selectinload(ParentProfile.children))
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = ParentProfile(user_id=user.id, fio=data.parent_fio, phone=data.phone)
        db.add(profile)
        await db.flush()
        child = ChildProfile(parent_id=profile.id, fio=data.child_fio, birth_date=data.child_birth_date)
        db.add(child)
        await db.flush()
    else:
        profile.fio = data.parent_fio
        profile.phone = data.phone
        if profile.children:
            profile.children[0].fio = data.child_fio
            profile.children[0].birth_date = data.child_birth_date
        else:
            new_child = ChildProfile(parent_id=profile.id, fio=data.child_fio, birth_date=data.child_birth_date)
            db.add(new_child)
            await db.flush()
    await db.commit()

    refetch = await db.execute(
        select(ParentProfile)
        .where(ParentProfile.user_id == user.id)
        .options(selectinload(ParentProfile.children))
    )
    profile = refetch.scalar_one()
    child_id = profile.children[0].id if profile.children else None
    logger.info("save_profile: user_id=%s child_id=%s children_count=%s", user.id, child_id, len(profile.children))
    return {"status": "ok", "child_id": child_id}


def _get_main_kb_for_notify():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    open_button = (
        InlineKeyboardButton(
            text="🏥 Открыть приложение",
            web_app=WebAppInfo(url=settings.WEB_APP_URL),
        )
        if settings.WEB_APP_URL.startswith("https://")
        else InlineKeyboardButton(
            text="🏥 Открыть приложение",
            url=settings.WEB_APP_URL,
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=[[open_button]])

@app.post("/api/progress")
async def update_progress(item_id: int, status: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Progress).where(Progress.item_id == item_id, Progress.user_id == user.id))
    progress = result.scalar_one_or_none()
    
    if not progress:
        progress = Progress(user_id=user.id, item_id=item_id, status=status)
        db.add(progress)
    else:
        progress.status = status
        progress.updated_at = datetime.utcnow()
        
    await db.commit()
    return {"status": "ok"}

@app.delete("/api/appointments/{appointment_id}")
async def cancel_appointment(
    appointment_id: int, 
    user: User = Depends(get_current_user), 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Appointment).where(Appointment.id == appointment_id, Appointment.user_id == user.id)
    )
    appointment = result.scalar_one_or_none()
    
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
        
    if appointment.status != "scheduled":
        raise HTTPException(status_code=400, detail="Appointment already cancelled or completed")
        
    if appointment.slot_datetime - datetime.utcnow() < timedelta(hours=24):
        raise HTTPException(status_code=400, detail="Cannot cancel less than 24h before appointment")

    try:
        await mis_provider.cancel_appointment(appointment.mis_external_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    appointment.status = "cancelled"
    await db.commit()
    return {"status": "ok"}

# Admin Routes
@app.get("/admin/tickets", response_class=HTMLResponse)
async def admin_tickets(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SupportTicket).options(joinedload(SupportTicket.user)).order_by(SupportTicket.created_at.desc())
    )
    tickets = result.scalars().all()
    return templates.TemplateResponse("admin/tickets.html", {
        "request": request, 
        "tickets": tickets,
        "active_page": "tickets"
    })

@app.post("/admin/tickets/{ticket_id}/close")
async def close_ticket(ticket_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket:
        ticket.status = "closed"
        await db.commit()
    return RedirectResponse(url="/admin/tickets", status_code=303)

# Progress & Content
@app.get("/api/modules", response_model=List[dict])
async def get_modules(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ContentModule).options(joinedload(ContentModule.items)))
    modules = result.scalars().unique().all()
    
    # Check purchases
    purchase_result = await db.execute(select(Purchase).where(Purchase.user_id == user.id, Purchase.status == "completed"))
    purchased_module_ids = [p.module_id for p in purchase_result.scalars().all()]
    
    return [
        {
            "id": m.id,
            "title": m.title,
            "description": m.description,
            "is_free": m.is_free,
            "price_stars": m.price_stars,
            "is_available": m.is_free or m.id in purchased_module_ids,
            "items_count": len(m.items)
        } for m in modules
    ]

@app.get("/api/modules/{module_id}/items")
async def get_module_items(module_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Check access
    module_result = await db.execute(select(ContentModule).where(ContentModule.id == module_id))
    module = module_result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
        
    if not module.is_free:
        purchase_result = await db.execute(select(Purchase).where(Purchase.user_id == user.id, Purchase.module_id == module_id, Purchase.status == "completed"))
        if not purchase_result.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Module not purchased")
            
    result = await db.execute(
        select(ContentItem, Progress.status)
        .outerjoin(Progress, (Progress.item_id == ContentItem.id) & (Progress.user_id == user.id))
        .where(ContentItem.module_id == module_id)
        .order_by(ContentItem.order)
    )
    
    items = []
    for item, status in result.all():
        items.append({
            "id": item.id,
            "type": item.type,
            "title": item.title,
            "url": item.url,
            "status": status or "not_started"
        })
    return items

# Payments (YooKassa)
@app.post("/api/purchases")
async def create_purchase(module_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Check if already purchased
    result = await db.execute(select(Purchase).where(Purchase.user_id == user.id, Purchase.module_id == module_id, Purchase.status == "completed"))
    if result.scalar_one_or_none():
        return {"status": "already_purchased"}
        
    module_result = await db.execute(select(ContentModule).where(ContentModule.id == module_id))
    module = module_result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    # In real world, we'd create YooKassa payment here
    # For MVP/Debug, we'll just create a pending purchase
    purchase = Purchase(user_id=user.id, module_id=module_id, status="pending")
    db.add(purchase)
    await db.commit()
    await db.refresh(purchase)
    
    # Simulate payment success for now
    if settings.DEBUG:
        purchase.status = "completed"
        await db.commit()
        return {"status": "success", "purchase_id": purchase.id}
    
    return {"status": "pending", "purchase_id": purchase.id}

@app.post("/api/payments/webhook")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # In real world, validate YooKassa signature and update purchase status
    data = await request.json()
    # ... logic to update purchase status ...
    return {"status": "ok"}
