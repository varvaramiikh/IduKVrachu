from datetime import datetime, date
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

# ── User ─────────────────────────────────────────────────────

class UserBase(BaseModel):
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None

class UserCreate(UserBase):
    pass

class User(UserBase):
    id: int
    consent_version: Optional[str] = None
    consent_timestamp: Optional[datetime] = None

    class Config:
        from_attributes = True

# ── Public catalog ────────────────────────────────────────────

class City(BaseModel):
    id: int
    name: str
    region: Optional[str] = None
    is_active: bool = True
    class Config:
        from_attributes = True

class Clinic(BaseModel):
    id: int
    name: str
    city_id: int
    address: Optional[str] = None
    phone: Optional[str] = None
    worktime: Optional[str] = None
    is_active: bool = True
    service_ids: List[int] = []

class Service(BaseModel):
    id: int
    clinic_id: int
    direction_id: int
    direction_name: Optional[str] = None
    direction_icon: Optional[str] = None
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    service_type: str
    is_active: bool = True

class Doctor(BaseModel):
    id: int
    name: str
    spec: Optional[str] = None
    clinic_id: Optional[int] = None
    exp_years: int = 0
    min_age: int = 0
    color: Optional[str] = None
    initials: Optional[str] = None
    avatar: Optional[str] = None
    is_active: bool = True
    class Config:
        from_attributes = True

class DoctorSlot(BaseModel):
    time: str
    busy: bool

class SlotSchema(BaseModel):
    datetime: datetime
    is_available: bool
    mis_external_id: str

# ── Appointments ──────────────────────────────────────────────

class AppointmentCreate(BaseModel):
    clinic_id: int
    service_id: int
    child_id: Optional[int] = None
    slot_datetime: datetime
    comment: Optional[str] = None

class Appointment(BaseModel):
    id: int
    clinic_id: int
    service_id: int
    child_id: Optional[int] = None
    slot_datetime: datetime
    status: str
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class AppointmentReschedule(BaseModel):
    slot_datetime: datetime

class AppointmentDetail(BaseModel):
    id: int
    service_id: int
    clinic_id: int
    service_name: str
    clinic_name: str
    slot_datetime: datetime
    status: str
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# ── Profile ───────────────────────────────────────────────────

class ProfileSaveRequest(BaseModel):
    parent_fio: str
    phone: str
    child_fio: str
    child_birth_date: date

class ProfileResponse(BaseModel):
    parent_fio: Optional[str] = None
    phone: Optional[str] = None
    child_fio: Optional[str] = None
    child_birth_date: Optional[date] = None
    child_id: Optional[int] = None

# ── Support ───────────────────────────────────────────────────

class SupportTicketCreate(BaseModel):
    message: str

class SupportTicket(BaseModel):
    id: int
    message: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

# ── Admin auth ────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    username: str
    password: str

# ── Admin directions ──────────────────────────────────────────

class AdminDirectionItem(BaseModel):
    id: int
    clinic_id: int
    clinic_name: str
    name: str
    desc: str
    icon: str
    color: str
    active: bool
    services_count: int
    content_count: int

class AdminDirectionCreate(BaseModel):
    clinic_id: Optional[int] = None  # superadmin must provide; clinic admin pinned to own
    name: str
    desc: str = ""
    icon: str = ""
    color: str = "#128395"
    active: bool = True
    also_in_clinic_ids: List[int] = []  # broadcast: создать копии в этих клиниках (super-only)

class AdminDirectionUpdate(BaseModel):
    name: str
    desc: str = ""
    icon: str = ""
    color: str = "#128395"
    active: bool = True
    also_in_clinic_ids: List[int] = []  # broadcast (super-only): создать копии в этих клиниках, если их там ещё нет

# ── Admin services ────────────────────────────────────────────

class AdminServiceItem(BaseModel):
    id: int
    direction_id: int
    direction_name: str
    clinic_id: int
    clinic_name: str
    name: str
    desc: str
    icon: str
    active: bool

class AdminServiceCreate(BaseModel):
    direction_id: int
    name: str
    desc: str = ""
    icon: str = ""
    active: bool = True
    also_in_clinic_ids: List[int] = []  # broadcast (super-only): создать копии в направлениях с тем же именем

class AdminServiceUpdate(BaseModel):
    direction_id: Optional[int] = None
    name: str
    desc: str = ""
    icon: str = ""
    active: bool = True
    also_in_clinic_ids: List[int] = []  # broadcast (super-only): копии в направлениях с тем же именем

# ── Admin cities ──────────────────────────────────────────────

class AdminCityItem(BaseModel):
    id: int
    name: str
    region: str
    active: bool
    clinicsCount: int

class AdminCityCreate(BaseModel):
    name: str
    region: str = ""
    active: bool = True

class AdminCityUpdate(AdminCityCreate):
    pass

# ── Admin clinics ─────────────────────────────────────────────

class AdminClinicItem(BaseModel):
    id: int
    name: str
    city: str
    city_id: int
    addr: str
    phone: str
    services: List[str]
    service_ids: List[int]
    directions_count: int = 0
    worktime: str
    active: bool

class AdminClinicCreate(BaseModel):
    name: str
    city_id: int
    addr: str = ""
    phone: str = ""
    worktime: str = ""
    active: bool = True

class AdminClinicUpdate(AdminClinicCreate):
    pass

# ── Admin doctors ─────────────────────────────────────────────

class AdminDoctorItem(BaseModel):
    id: int
    name: str
    spec: str
    clinic: str
    clinic_id: Optional[int]
    exp: int
    minAge: int
    color: str
    initials: str
    avatar: Optional[str] = None
    active: bool

class AdminDoctorCreate(BaseModel):
    name: str
    spec: str = ""
    clinic_id: Optional[int] = None
    exp: int = 0
    minAge: int = 0
    color: str = "#16a085"
    initials: str = ""
    avatar: Optional[str] = None
    active: bool = True

class AdminDoctorUpdate(AdminDoctorCreate):
    pass

# ── Admin doctor schedule ─────────────────────────────────────

class AdminScheduleUpdate(BaseModel):
    # {day_index_str: {time_slot: bool}}
    slots: Dict[str, Dict[str, bool]]

# ── Admin content ─────────────────────────────────────────────

class AdminContentItem(BaseModel):
    id: int
    direction_name: str
    type: str
    title: str
    desc: str
    duration: Optional[int]
    url: str
    active: bool

class AdminContentCreate(BaseModel):
    direction_name: str
    type: str = "Мультфильм"
    title: str
    desc: str = ""
    duration: Optional[int] = None
    url: str = ""
    active: bool = True

class AdminContentUpdate(BaseModel):
    direction_name: Optional[str] = None
    type: str = "Мультфильм"
    title: str
    desc: str = ""
    duration: Optional[int] = None
    url: str = ""
    active: bool = True

# ── Admin roles ───────────────────────────────────────────────

class AdminRoleItem(BaseModel):
    id: int
    name: str
    desc: str
    color: str
    perms: Dict[str, List[int]]

class AdminRoleCreate(BaseModel):
    name: str
    desc: str = ""
    color: str = "#2980b9"
    perms: Dict[str, List[int]] = {}

class AdminRoleUpdate(AdminRoleCreate):
    pass

# ── Admin stats ───────────────────────────────────────────────

class AdminStats(BaseModel):
    services_count: int
    directions_count: int
    cities_count: int
    clinics_count: int
    doctors_count: int
    content_count: int
    users_count: int
    appointments_count: int

# ── Admin users (super-admin manages clinic admins) ───────────

class AdminMe(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    is_superadmin: bool
    clinic_id: Optional[int] = None
    clinic_name: Optional[str] = None

class AdminUserItem(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    is_superadmin: bool
    clinic_id: Optional[int] = None
    clinic_name: Optional[str] = None
    is_active: bool

class AdminUserCreate(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = ""
    is_superadmin: bool = False
    clinic_id: Optional[int] = None
    is_active: bool = True

# ── Admin notifications ───────────────────────────────────────

class AdminNotificationItem(BaseModel):
    id: int
    clinic_id: int
    clinic_name: str
    type: str
    title: str
    body: Optional[str] = None
    appointment_id: Optional[int] = None
    is_read: bool
    created_at: datetime

# ── Admin appointments ────────────────────────────────────────

class AdminAppointmentItem(BaseModel):
    id: int
    clinic_id: int
    clinic_name: str
    service_id: int
    service_name: str
    child_id: Optional[int] = None
    child_name: str = ""
    parent_name: str = ""
    parent_phone: str = ""
    user_telegram_id: Optional[int] = None
    slot_datetime: datetime
    status: str
    comment: Optional[str] = None
    created_at: datetime


class AdminUserUpdate(BaseModel):
    username: str
    password: Optional[str] = None
    full_name: Optional[str] = ""
    is_superadmin: bool = False
    clinic_id: Optional[int] = None
    is_active: bool = True
