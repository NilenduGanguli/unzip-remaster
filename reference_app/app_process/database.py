from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from pydantic_settings import BaseSettings
import os
import oracledb
import logging

try:
    oracledb.init_oracle_client()
except Exception as e:
    logging.warning(f"Failed to initialize Oracle Client (Thick Mode): {e}. Proceeding, but connection functionality might be limited.")

class Settings(BaseSettings):
    DB_USERNAME: str = os.getenv("DB_USERNAME", "system")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "oracle")
    # Python oracle driver URL format
    # oracle+oracledb://user:pass@host:port/?service_name=SERVICE
    DB_HOST: str = os.getenv("DB_HOST", "oracle-server")
    DB_PORT: str = os.getenv("DB_PORT", "1521")
    DB_SERVICE: str = os.getenv("DB_SERVICE", "FREEPDB1")
    
    # Constructed URL
    @property
    def DATABASE_URL(self) -> str:
        return f"oracle+oracledb://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/?service_name={self.DB_SERVICE}"

    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8080"))
    DOCUMENTUM_FETCH_URL: str = os.getenv("DOCUMENTUM_FETCH_URL", "http://documentum:8000/fetch")
    DOCUMENTUM_UPLOAD_URL: str = os.getenv("DOCUMENTUM_UPLOAD_URL", "http://documentum:8000/upload")
    UNZIP_UPLOAD_THREADS: int = int(os.getenv("UNZIP_UPLOAD_THREADS", "10"))

    # Certificate Settings
    USE_CERT: bool = os.getenv("USE_CERT", "false").lower() == "true"
    DOCUMENTUM_CERT_PATH: str = os.getenv("DOCUMENTUM_CERT_PATH", "")
    DOCUMENTUM_KEY_PATH: str = os.getenv("DOCUMENTUM_KEY_PATH", "")
    DOCUMENTUM_KEY_PASSWORD: str = os.getenv("DOCUMENTUM_KEY_PASSWORD", "")

    # Directory to store temp files (Initial upload)
    TEMP_DIR: str = "/tmp/unzipper_upload"
    
    # PVC Directory for unzipped content
    PVC_DIR: str = os.getenv("PVC_DIR", "./unzip-pvc-data")

settings = Settings()

# Performance tuning: pool size
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_recycle=3600,
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
