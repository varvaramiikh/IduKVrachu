from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from .config import settings

engine = create_async_engine(settings.DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db():
    async with async_session() as session:
        yield session


def ensure_storage() -> None:
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        return
    _, sep, path = url.partition(":///")
    if not sep or not path or path == ":memory:":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
