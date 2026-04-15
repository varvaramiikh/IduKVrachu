from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

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

class AppointmentCreate(BaseModel):
    clinic_id: int
    service_id: int
    child_id: int
    slot_datetime: datetime
    comment: Optional[str] = None

class Appointment(BaseModel):
    id: int
    clinic_id: int
    service_id: int
    child_id: int
    slot_datetime: datetime
    status: str
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class SupportTicketCreate(BaseModel):
    message: str

class SupportTicket(BaseModel):
    id: int
    message: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
