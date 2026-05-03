from datetime import datetime, date
from typing import List, Optional
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Date, Float, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    first_name: Mapped[Optional[str]] = mapped_column(String(255))

    consent_version: Mapped[Optional[str]] = mapped_column(String(50))
    consent_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime)

    parent_profile = relationship("ParentProfile", back_populates="user", uselist=False)
    appointments = relationship("Appointment", back_populates="user")
    bot_appointments = relationship("BotAppointmentRequest", back_populates="user")
    purchases = relationship("Purchase", back_populates="user")
    progress = relationship("Progress", back_populates="user")
    tickets = relationship("SupportTicket", back_populates="user")

class ParentProfile(Base):
    __tablename__ = "parent_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    fio: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(20))

    user = relationship("User", back_populates="parent_profile")
    children = relationship("ChildProfile", back_populates="parent")

class ChildProfile(Base):
    __tablename__ = "child_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parent_profiles.id"))
    fio: Mapped[str] = mapped_column(String(255))
    birth_date: Mapped[date] = mapped_column(Date)

    parent = relationship("ParentProfile", back_populates="children")
    appointments = relationship("Appointment", back_populates="child")

class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    region: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mis_external_id: Mapped[Optional[str]] = mapped_column(String(100))

    clinics = relationship("Clinic", back_populates="city")

class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(512))
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    worktime: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mis_external_id: Mapped[Optional[str]] = mapped_column(String(100))

    city = relationship("City", back_populates="clinics")
    appointments = relationship("Appointment", back_populates="clinic")
    doctors = relationship("Doctor", back_populates="clinic")
    services = relationship("Service", back_populates="clinic", cascade="all, delete-orphan")
    admins = relationship("AdminUser", back_populates="clinic")

class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    icon: Mapped[Optional[str]] = mapped_column(String(10))
    service_type: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mis_external_id: Mapped[Optional[str]] = mapped_column(String(100))

    clinic = relationship("Clinic", back_populates="services")
    appointments = relationship("Appointment", back_populates="service")

class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    child_id: Mapped[int] = mapped_column(ForeignKey("child_profiles.id"))

    slot_datetime: Mapped[datetime] = mapped_column(DateTime)
    mis_external_id: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="scheduled")
    comment: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="appointments")
    clinic = relationship("Clinic", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    child = relationship("ChildProfile", back_populates="appointments")

class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    spec: Mapped[Optional[str]] = mapped_column(String(255))
    clinic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clinics.id"), nullable=True)
    exp_years: Mapped[int] = mapped_column(Integer, default=0)
    min_age: Mapped[int] = mapped_column(Integer, default=0)
    color: Mapped[Optional[str]] = mapped_column(String(20))
    initials: Mapped[Optional[str]] = mapped_column(String(10))
    avatar: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    clinic = relationship("Clinic", back_populates="doctors")
    schedule_slots = relationship("DoctorSchedule", back_populates="doctor", cascade="all, delete-orphan")

class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    day_of_week: Mapped[int] = mapped_column(Integer)   # 0=Mon … 6=Sun
    time_slot: Mapped[str] = mapped_column(String(5))   # "HH:MM"

    doctor = relationship("Doctor", back_populates="schedule_slots")

class AdminRole(Base):
    __tablename__ = "admin_roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(500))
    color: Mapped[Optional[str]] = mapped_column(String(20))
    perms: Mapped[str] = mapped_column(Text, default="{}")  # JSON: {section: [read,create,edit,delete]}

class ContentModule(Base):
    __tablename__ = "content_modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    service_id: Mapped[Optional[int]] = mapped_column(ForeignKey("services.id"), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(100))
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    url: Mapped[Optional[str]] = mapped_column(String(512))
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    price_stars: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    items = relationship("ContentItem", back_populates="module")
    purchases = relationship("Purchase", back_populates="module")

class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("content_modules.id"))
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[Optional[str]] = mapped_column(String(512))
    order: Mapped[int] = mapped_column(Integer, default=0)

    module = relationship("ContentModule", back_populates="items")
    progress = relationship("Progress", back_populates="item")

class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    module_id: Mapped[int] = mapped_column(ForeignKey("content_modules.id"))
    payment_id: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="purchases")
    module = relationship("ContentModule", back_populates="purchases")

class Progress(Base):
    __tablename__ = "progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"))
    status: Mapped[str] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="progress")
    item = relationship("ContentItem", back_populates="progress")

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(50), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="tickets")

class BotAppointmentRequest(Base):
    __tablename__ = "bot_appointment_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    city: Mapped[str] = mapped_column(String(100))
    clinic_name: Mapped[str] = mapped_column(String(255))
    desired_date: Mapped[str] = mapped_column(String(20))
    time_range: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="bot_appointments")

class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    clinic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clinics.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    clinic = relationship("Clinic", back_populates="admins")


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(255))
    entity: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
