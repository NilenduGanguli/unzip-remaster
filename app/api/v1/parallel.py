from fastapi import APIRouter, Depends, HTTPException
from typing import Dict
from app.services.v1.unzip_files import UnzipWorkflowService, get_workflow_service
from app.models.v1.unzip import UnzipDetail
from app.core.v1.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

@router.get("/unzip_doc_parallel/{clientId}/{documentLinkId}", response_model=Dict[str, UnzipDetail])
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
