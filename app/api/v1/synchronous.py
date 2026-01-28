from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from typing import Dict
from app.services.v1.unzip_files import UnzipWorkflowService, get_workflow_service
from app.models.v1.unzip import UnzipDetail
from app.documentum.v1.client import get_documentum_client
from app.core.v1.logging import get_logger
import base64

logger = get_logger(__name__)

router = APIRouter()

@router.post("/unzip_upload_doc/{client_id}", response_model=Dict[str, UnzipDetail])
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
        return await workflow.process_direct_upload(file, client_id)
    except Exception as e:
        await logger.aerror(f"Endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/unzip_upload_save_doc/{clientId}/{documentLinkId}", response_model=Dict[str, UnzipDetail])
async def unzip_upload_save_doc(
    clientId: str,
    documentLinkId: str,
    workflow: UnzipWorkflowService = Depends(get_workflow_service)
):
    try:
        return await workflow.process_document_unzip(documentLinkId, clientId)
    except Exception as e:
        await logger.aerror(f"Error in unzip_upload_save_doc: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/fetch_file_documentum/{documentLinkId}")
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
         await logger.aerror(f"Error fetching document: {e}")
         raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health():
    return {"status": "up", "mode": "async-logging"}

application = type('Application', (object,), {'router': router})
