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

class CityBase(BaseModel):
    name: str
    is_active: bool = True

class City(CityBase):
    id: int
    class Config:
        from_attributes = True

class ClinicBase(BaseModel):
    name: str
    address: Optional[str] = None
    city_id: int
    is_active: bool = True

class Clinic(ClinicBase):
    id: int
    class Config:
        from_attributes = True

class ServiceBase(BaseModel):
    name: str
    service_type: str
    is_active: bool = True

class Service(ServiceBase):
    id: int
    class Config:
        from_attributes = True

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

# ── Admin services ────────────────────────────────────────────

class AdminServiceItem(BaseModel):
    id: int
    name: str
    desc: str
    icon: str
    active: bool

class AdminServiceCreate(BaseModel):
    name: str
    desc: str = ""
    icon: str = ""
    active: bool = True

class AdminServiceUpdate(AdminServiceCreate):
    pass

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
    worktime: str
    active: bool

class AdminClinicCreate(BaseModel):
    name: str
    city_id: int
    addr: str = ""
    phone: str = ""
    service_ids: List[int] = []
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
    active: bool

class AdminDoctorCreate(BaseModel):
    name: str
    spec: str = ""
    clinic_id: Optional[int] = None
    exp: int = 0
    minAge: int = 0
    color: str = "#16a085"
    initials: str = ""
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
    service: str
    service_id: Optional[int]
    type: str
    title: str
    desc: str
    duration: Optional[int]
    url: str
    active: bool

class AdminContentCreate(BaseModel):
    service_id: Optional[int] = None
    type: str = "Мультфильм"
    title: str
    desc: str = ""
    duration: Optional[int] = None
    url: str = ""
    active: bool = True

class AdminContentUpdate(AdminContentCreate):
    pass

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
    cities_count: int
    clinics_count: int
    doctors_count: int
    content_count: int
    users_count: int
    appointments_count: int
