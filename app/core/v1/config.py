from pydantic_settings import BaseSettings
import os
import logging

_module_logger = "SETUP"
logger = logging.getLogger(_module_logger)


class DatabaseSettings(BaseSettings):
    DB_USERNAME: str = os.getenv("DB_USERNAME")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD")
    # Python oracle driver URL format
    # oracle+oracledb://user:pass@host:port/?service_name=SERVICE
    DB_HOST: str = os.getenv("DB_HOST")
    DB_PORT: str = os.getenv("DB_PORT")
    DB_SERVICE: str = os.getenv("DB_SERVICE")
    
    # Constructed URL
    @property
    def DATABASE_URL(self) -> str:
        return f"oracle+oracledb://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/?service_name={self.DB_SERVICE}"
    
    # DB Pool Config
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "3600"))

class DocumentumSettings(BaseSettings):
    # Documentum API Endpoints
    DOCUMENTUM_FETCH_URL: str = os.getenv("DOCUMENTUM_FETCH_URL")
    DOCUMENTUM_UPLOAD_URL: str = os.getenv("DOCUMENTUM_UPLOAD_URL")
    
    # Client Config
    DOCUMENTUM_TIMEOUT: float = float(os.getenv("DOCUMENTUM_TIMEOUT", "30.0"))
    DOCUMENTUM_MAX_CONNECTIONS: int = int(os.getenv("DOCUMENTUM_MAX_CONNECTIONS", "100"))
    DOCUMENTUM_MAX_KEEPALIVE: int = int(os.getenv("DOCUMENTUM_MAX_KEEPALIVE", "50"))

    # Certificate Settings
    USE_CERT: bool = os.getenv("USE_CERT", "false").lower() == "true"
    DOCUMENTUM_CERT_PATH: str = os.getenv("DOCUMENTUM_CERT_PATH", "")
    DOCUMENTUM_KEY_PATH: str = os.getenv("DOCUMENTUM_KEY_PATH", "")

class BucketSettings(BaseSettings):
    # S3 Bucket Settings
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "")
    S3_HOST: str = os.getenv("S3_HOST", "")
    S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY", "")
    S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY", "")

class AppSettings(BaseSettings):
    app_name: str = os.getenv("APP_NAME", "Unzip Service")
    app_version: str = os.getenv("APP_VERSION", "1.0.0")
    app_region: str = os.getenv("APP_REGION", "nam")
    debug_mode: bool = os.getenv("DEBUG_MODE", "false").lower() == "true"
    dev_mode: bool = os.getenv("DEV_MODE", "false").lower() == "true"

    # Directory to store temp files (Initial upload)
    TEMP_DIR: str = "/tmp/unzipper_upload"
    
    # PVC Directory for unzipped content
    PVC_DIR: str = os.getenv("PVC_DIR", "./unzip-pvc-data")
    
    # Process Pool Config
    UNZIP_MAX_WORKERS: int = int(os.getenv("UNZIP_MAX_WORKERS", "1"))

    # Helper Services
    FILE_HANDLER_SERVICE_URL: str = os.getenv("FILE_HANDLER_SERVICE_URL", "http://document-handler:8080/upload/pvc/files")


