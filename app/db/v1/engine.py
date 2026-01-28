from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import oracledb
from app.core.v1.config import DatabaseSettings
from app.core.v1.logging import get_logger

_module_logger = "DATABASE"
logger = get_logger(_module_logger)

async def oracle_thick_client():
    try:
        oracledb.init_oracle_client()
        await logger.ainfo("Oracle Client initialized in Thick Mode.")
    except Exception as e:
        await logger.awarning(f"Failed to initialize Oracle Client (Thick Mode): {e}. Proceeding, but connection functionality might be limited.")

settings = DatabaseSettings()

# Performance tuning: pool size
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session