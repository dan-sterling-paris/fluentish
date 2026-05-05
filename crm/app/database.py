from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import settings
from app.models import Base


def _get_database_url() -> str:
    url = settings.database_url
    # Railway (and some other PaaS) inject postgres:// which SQLAlchemy rejects.
    # Rewrite to the asyncpg dialect SQLAlchemy expects.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


_db_url = _get_database_url()
_is_sqlite = _db_url.startswith("sqlite")

_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_async_engine(
    _db_url,
    echo=False,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

if _is_sqlite:
    from sqlalchemy import event as _sa_event
    from sqlalchemy.engine import Engine as _Engine

    @_sa_event.listens_for(_Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
