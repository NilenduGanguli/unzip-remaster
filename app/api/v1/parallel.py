"""
Parallel API Routes (V1).
Provides endpoints for parallel processing utilizing the File Handler Service.
- /unzip_upload_doc_parallel: Direct upload and parallel processing via external service.
- /unzip_upload_save_doc_parallel: Fetch from Documentum and parallel processing.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from typing import Dict
from app.services.v1.unzip_files import UnzipWorkflowService, get_workflow_service
from app.models.v1.unzip import UnzipDetail
from app.core.v1.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

@router.post("/unzip_upload_doc_parallel/{client_id}", response_model=Dict[str, UnzipDetail])
async def unzip_upload_doc_parallel(
    client_id: str,
    file: UploadFile = File(...),
    workflow: UnzipWorkflowService = Depends(get_workflow_service)
):
    if not client_id:
        raise HTTPException(status_code=400, detail="Client ID is required")
    
    if not file:
        raise HTTPException(status_code=400, detail="File is required")
        
    try:
        return await workflow.process_direct_upload_parallel(file, client_id)
    except Exception as e:
        await logger.aerror(f"Endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/unzip_upload_save_doc_parallel/{clientId}/{documentLinkId}", response_model=Dict[str, UnzipDetail])
async def unzip_doc_parallel(
    clientId: str,
    documentLinkId: str,
    workflow: UnzipWorkflowService = Depends(get_workflow_service)
):
    try:
        return await workflow.process_document_unzip_parallel(documentLinkId, clientId)
    except HTTPException as e:
        raise e
    except Exception as e:
        await logger.aerror(f"Error in unzip_doc_parallel: {e}")
        raise HTTPException(status_code=500, detail=str(e))

application = type('Application', (object,), {'router': router})
