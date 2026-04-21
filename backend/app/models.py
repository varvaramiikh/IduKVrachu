from datetime import datetime, date
from typing import List, Optional
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Date, Float
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mis_external_id: Mapped[Optional[str]] = mapped_column(String(100))
    
    clinics = relationship("Clinic", back_populates="city")

class Clinic(Base):
    __tablename__ = "clinics"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[Optional[str]] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mis_external_id: Mapped[Optional[str]] = mapped_column(String(100))
    
    city = relationship("City", back_populates="clinics")
    appointments = relationship("Appointment", back_populates="clinic")

class Service(Base):
    __tablename__ = "services"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    service_type: Mapped[str] = mapped_column(String(100)) # e.g. "стоматология"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mis_external_id: Mapped[Optional[str]] = mapped_column(String(100))
    
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
    status: Mapped[str] = mapped_column(String(50), default="scheduled") # scheduled, cancelled, completed
    comment: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="appointments")
    clinic = relationship("Clinic", back_populates="appointments")
    service = relationship("Service", back_populates="appointments")
    child = relationship("ChildProfile", back_populates="appointments")

class ContentModule(Base):
    __tablename__ = "content_modules"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(1000))
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    price_stars: Mapped[int] = mapped_column(Integer, default=0)
    
    items = relationship("ContentItem", back_populates="module")
    purchases = relationship("Purchase", back_populates="module")

class ContentItem(Base):
    __tablename__ = "content_items"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("content_modules.id"))
    type: Mapped[str] = mapped_column(String(50)) # video, story, game
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
    status: Mapped[str] = mapped_column(String(50), default="pending") # pending, completed, failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="purchases")
    module = relationship("ContentModule", back_populates="purchases")

class Progress(Base):
    __tablename__ = "progress"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"))
    status: Mapped[str] = mapped_column(String(50)) # opened, completed
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="progress")
    item = relationship("ContentItem", back_populates="progress")

class SupportTicket(Base):
    __tablename__ = "support_tickets"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(50), default="open") # open, closed, in_progress
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="tickets")

class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer) # For simplicity, can be a user_id with admin role
    action: Mapped[str] = mapped_column(String(255))
    entity: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
