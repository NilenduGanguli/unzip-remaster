from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os
import shutil
import base64
from typing import Dict, Any

from app_process.database import engine, settings, Base
from app_process.documentum_client import close_documentum_client
from app_process.service import UnzipWorkflowService,get_workflow_service, get_documentum_client
from app_process.models import UnzipDetail

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("unzipper-service-process")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Unzip Service (ProcessPool Version)")
    
    # Initialize DB Tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Ensure PVC Dir exists
    if not os.path.exists(settings.PVC_DIR):
        try:
            os.makedirs(settings.PVC_DIR)
            logger.info(f"Created PVC directory at {settings.PVC_DIR}")
        except Exception as e:
            logger.error(f"Failed to create PVC directory: {e}")

    yield
    # Shutdown
    logger.info("Shutting down...")
    await close_documentum_client()
    await engine.dispose()
    # Process Pool shuts down automatically on exit usually, or we can explicitely shut it down if we stored reference globally

app = FastAPI(lifespan=lifespan)

@app.post("/unzip_upload_doc/{client_id}", response_model=Dict[str, UnzipDetail])
async def unzip_upload_doc(
    client_id: str,
    file: UploadFile = File(...),
    workflow: UnzipWorkflowService = Depends(get_workflow_service)
):
    if not client_id:
        raise HTTPException(status_code=400, detail="Client ID is required")
    
    if not file:
        raise HTTPException(status_code=400, detail="File is required")
        
    try:
        result = await workflow.process_direct_upload(file, client_id)
        return result
    except Exception as e:
        logger.error(f"Endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/unzip_upload_save_doc/{clientId}/{documentLinkId}", response_model=Dict[str, UnzipDetail])
async def unzip_upload_save_doc(
    clientId: str,
    documentLinkId: str,
    workflow: UnzipWorkflowService = Depends(get_workflow_service)
):
    try:
        return await workflow.process_document_unzip(documentLinkId, clientId)
    except Exception as e:
        logger.error(f"Error in unzip_upload_save_doc: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fetch_file_documentum/{documentLinkId}")
async def fetch_file_documentum(
    documentLinkId: str,
    doc_client = Depends(get_documentum_client)
):
    try:
        filename, content = await doc_client.fetch_document(documentLinkId)
        encoded = base64.b64encode(content).decode('utf-8')
        return {
            "filename": filename,
            "content": encoded 
        }
    except Exception as e:
         logger.error(f"Error fetching document: {e}")
         raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "up", "mode": "process-pool"}
