from fastapi import FastAPI
from contextlib import asynccontextmanager
import os
from app.core.v1.config import AppSettings
from app.core.v1.logging import setup_logging,get_logger
from app.db.v1.engine import Base, engine,oracle_thick_client
from app.api.v1.synchronous import router as synchronous_router
from app.api.v1.parallel import router as parallel_router
from app.api.v1.asynchronous import router as asynchronous_router
from app.documentum.v1.client import close_documentum_client

_module_logger = "SERVER"

#before app startup
setup_logging()
logger = get_logger(_module_logger)
settings = AppSettings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await logger.ainfo("Starting Unzip Service (ProcessPool Version)")
    await oracle_thick_client()
    
    # Initialize DB Tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
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
    await engine.dispose()
    # Process Pool shuts down automatically on exit usually, or we can explicitely shut it down if we stored reference globally

app = FastAPI(title=settings.app_name,lifespan=lifespan)


# Register routes
app.include_router(synchronous_router, prefix="/api/v1")
app.include_router(parallel_router, prefix="/api/v1")
app.include_router(asynchronous_router, prefix="/api/v2")

@app.get("/health")
async def health():
    return {"status": "up", "mode": "async-logging", "location": "root"}
