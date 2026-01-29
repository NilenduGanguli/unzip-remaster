from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, Form
from typing import Optional
from app.documentum.v1.client import get_documentum_client
from app.buckets.v1.client import get_s3_client, S3Client
from app.core.v1.logging import get_logger
import uuid
import os

logger = get_logger(__name__)

router = APIRouter()

@router.get("/fetch_file_documentum/{documentLinkId}")
async def fetch_file_documentum(
    documentLinkId: str,
    doc_client = Depends(get_documentum_client)
):
    try:
        filename, content = await doc_client.fetch_document(documentLinkId)
        
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Filename": filename
        }
        
        return Response(content=content, media_type="application/octet-stream", headers=headers)
        
    except Exception as e:
         await logger.aerror(f"Error fetching document: {e}")
         raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload_file_documentum")
async def upload_file_documentum(
    file: UploadFile = File(...),
    doc_client = Depends(get_documentum_client)
):
    try:
        content = await file.read()
        doc_id = await doc_client.upload_document(content, file.filename)
        return {"documentLinkId": doc_id}
    except Exception as e:
        await logger.aerror(f"Error uploading to Documentum: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/fetch_file_s3/{s3_path:path}")
async def fetch_file_s3(
    s3_path: str,
    s3_client: S3Client = Depends(get_s3_client)
):
    """
    Fetches raw file from S3. 
    Accepts full 's3://bucket/key/...' path.
    """
    try:
        content, content_type = await s3_client.get_file(s3_path)
        filename = os.path.basename(s3_path)
        
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Filename": filename
        }
        return Response(content=content, media_type="application/octet-stream", headers=headers)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found in S3")
    except Exception as e:
        await logger.aerror(f"Error fetching from S3: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload_file_s3")
async def upload_file_s3(
    file: UploadFile = File(...),
    file_path: Optional[str] = Form(None),
    s3_client: S3Client = Depends(get_s3_client)
):
    try:
        content = await file.read()
        
        if file_path:
            # S3 keys shouldn't start with / typically, but we can strip it to be safe
            # or just use as is if user insists. 
            # Boto3 usually handles it but it's cleaner to remove leading slash.
            key = file_path.lstrip('/')
            
            # If path ends in slash, it's a directory, append filename
            if key.endswith('/'):
                key = f"{key}{file.filename}"
        else:
             # Default: Generate a unique key
             key = f"uploads/{uuid.uuid4()}/{file.filename}"
        
        s3_path = await s3_client.upload_file(key, content, file.content_type)
        return {
            "file_path": key,
            "s3_path": s3_path
        }
    except Exception as e:
        await logger.aerror(f"Error uploading to S3: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
application = type('Application', (object,), {'router': router})