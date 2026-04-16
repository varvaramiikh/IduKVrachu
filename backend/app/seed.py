from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import async_session
from .models import City, Clinic, Service, ContentModule, ContentItem


async def _is_empty(db: AsyncSession) -> bool:
    result = await db.execute(select(City.id).limit(1))
    return result.first() is None


async def seed_if_empty() -> None:
    async with async_session() as db:
        if not await _is_empty(db):
            return

        moscow = City(name="Москва", is_active=True, mis_external_id="msk_01")
        db.add(moscow)
        await db.flush()

        clinic1 = Clinic(name="Детская стоматология 'Зубная фея'", address="ул. Пушкина, д. 10", city_id=moscow.id, is_active=True, mis_external_id="cl_01")
        clinic2 = Clinic(name="Медицинский центр 'Здоровье'", address="пр. Мира, д. 25", city_id=moscow.id, is_active=True, mis_external_id="cl_02")
        db.add_all([clinic1, clinic2])

        s1 = Service(name="Первичный осмотр стоматолога", service_type="стоматология", is_active=True, mis_external_id="srv_01")
        s2 = Service(name="Лечение кариеса", service_type="стоматология", is_active=True, mis_external_id="srv_02")
        s3 = Service(name="Забор крови из вены", service_type="анализы", is_active=True, mis_external_id="srv_03")
        db.add_all([s1, s2, s3])

        m1 = ContentModule(title="Сдача крови", description="Подготовка к анализу крови", is_free=True)
        m2 = ContentModule(title="Стоматолог", description="Знакомство с кабинетом стоматолога", is_free=False, price_stars=69)
        db.add_all([m1, m2])
        await db.flush()

        db.add_all([
            ContentItem(module_id=m1.id, type="video", title="Иду сдавать кровь", order=1),
            ContentItem(module_id=m1.id, type="story", title="Социстория: Кровь из вены", order=2),
            ContentItem(module_id=m2.id, type="video", title="Мой первый визит к стоматологу", order=1),
            ContentItem(module_id=m2.id, type="story", title="Социстория: У стоматолога", order=2),
            ContentItem(module_id=m2.id, type="game", title="Игра: Полечи зубки", order=3),
        ])

        await db.commit()
