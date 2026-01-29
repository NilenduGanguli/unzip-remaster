"""
Asynchronous API Routes (V2).
Provides optimized asynchronous endpoints using asyncio and thread/process pools.
- /unzip_upload_doc: Direct upload with concurrent upstream uploads.
- /unzip_upload_save_doc: Fetch from Documentum with concurrent upstream uploads.
"""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from typing import Dict
from app.services.v1.unzip_files import UnzipWorkflowService, get_workflow_service
from app.models.v1.unzip import UnzipDetail
from app.core.v1.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

@router.post("/unzip_upload_doc/{client_id}", response_model=Dict[str, UnzipDetail])
async def unzip_upload_doc(
    client_id: str,
    file: UploadFile = File(...),
    workflow: UnzipWorkflowService = Depends(get_workflow_service)
):
    """
    Optimized asynchronous endpoint for direct file upload and extraction.
    Uses concurrent uploads to Documentum.
    """
    if not client_id:
        raise HTTPException(status_code=400, detail="Client ID is required")
    
    if not file:
        raise HTTPException(status_code=400, detail="File is required")
        
    try:
        return await workflow.process_direct_upload_optimized(file, client_id)
    except Exception as e:
        await logger.aerror(f"Async Endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/unzip_upload_save_doc/{clientId}/{documentLinkId}", response_model=Dict[str, UnzipDetail])
async def unzip_upload_save_doc(
    clientId: str,
    documentLinkId: str,
    workflow: UnzipWorkflowService = Depends(get_workflow_service)
):
    """
    Optimized asynchronous endpoint for processing existing Documentum documents.
    Uses concurrent uploads to Documentum.
    """
    try:
        return await workflow.process_document_unzip_optimized(documentLinkId, clientId)
    except Exception as e:
        await logger.aerror(f"Error in async unzip_upload_save_doc: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health():
    return {"status": "up", "mode": "async-optimized", "location": "asynchronous"}

application = type('Application', (object,), {'router': router})
