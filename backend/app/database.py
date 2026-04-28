from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from .config import settings

engine = create_async_engine(settings.DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=134217728")
        cursor.close()


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
