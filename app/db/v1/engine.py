from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
import cx_Oracle
from app.core.v1.config import DatabaseSettings
from app.core.v1.logging import get_logger

_module_logger = "DATABASE"
logger = get_logger(_module_logger)

settings = DatabaseSettings()

# cx_Oracle depends on Oracle Client libraries being present.

# Performance tuning: pool size
engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
    autoflush=False
)

class Base(DeclarativeBase):
    pass

def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()