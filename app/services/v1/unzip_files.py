
import asyncio
import os
import uuid
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

import aiofiles
import httpx
from fastapi import UploadFile, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.v1.config import AppSettings
from app.db.v1.engine import get_db
from app.db.v1.schema import KycDocumentUnzip
from app.documentum.v1.client import DocumentumClient, get_documentum_client
from app.models.v1.unzip import (
    UnzipDetail, UnzippedFileDetail, ZipNode
)
from app.services.v1.zip_processor import ZipProcessor
from app.services.v1.upload_manager import UploadManager
from app.buckets.v1.client import S3Client
from app.core.v1.logging import get_logger

logger = get_logger(__name__)
settings = AppSettings()

class UnzipWorkflowService:
    def __init__(self, db: Session, doc_client: DocumentumClient):
        self.db = db
        self.doc_client = doc_client
        self.s3_client = S3Client()
        self.pvc_dir = Path(settings.PVC_DIR)
        self.temp_dir = Path(settings.TEMP_DIR)
        
        self.zip_processor = ZipProcessor()
        self.upload_manager = UploadManager(db, doc_client)
        
        # Ensure directories exist
        self.pvc_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def _cache_response(self, response: Dict[str, UnzipDetail], root_doc_id: str, client_id: str):
        """Uploads final response to S3 and updates DB record."""
        if not settings.UNZIP_ENABLE_CACHE:
            return

        try:
            # Convert to dict for JSON serialization
            json_data = {k: v.dict(by_alias=True) for k, v in response.items()}
            
            key = f"{settings.S3_KEY_PREFIX}/unzip_responses/{client_id}/{root_doc_id}.json"
            s3_path = await self.s3_client.upload_json(key, json_data)
            
            # Update DB with S3 path - Update ALL matching records for this client/doc_id to ensure consistency
            stmt = select(KycDocumentUnzip).where(
                KycDocumentUnzip.document_link_id == root_doc_id,
                KycDocumentUnzip.client_id == client_id
            )
            result = self.db.execute(stmt)
            records = result.scalars().all()
            
            if records:
                for record in records:
                    record.document_s3_path = s3_path
                self.db.commit()
            else:
                await logger.awarning(f"Root record {root_doc_id} for client {client_id} not found for S3 path update")
                
        except Exception as e:
            await logger.aerror(f"Failed to cache response to S3: {e}")

    async def _build_response_from_cache(self, existing: List[KycDocumentUnzip], document_link_id: str, client_id: str) -> Optional[Dict[str, UnzipDetail]]:
        """
        Try to reconstruct the UnzipDetail response from S3 Cache.
        Returns None if cache is invalid or missing, prompting re-processing.
        """
        # 1. Try S3 Cache
        root_record = next((r for r in existing if r.document_link_id == document_link_id), None)
        if root_record and root_record.document_s3_path:
            try:
                data = await self.s3_client.get_json(root_record.document_s3_path)
                if data:
                    parsed_response = {}
                    for k, v in data.items():
                        parsed_response[k] = UnzipDetail(**v)
                    await logger.ainfo(f"Returned S3 cached result for {document_link_id}")
                    return parsed_response
            except Exception as e:
                await logger.aerror(f"S3 Cache miss/error: {e}")

        # 2. If S3 failed or no path, return None to trigger original flow
        return None

    async def process_direct_upload(self, file: UploadFile, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Entry point for direct file upload:
        1. Save upload to temp
        2. Unzip (CPU bound)
        3. Upload extracted parts to Documentum
        4. Commit DB
        """
        # Save uploaded file
        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{file.filename}"
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
            
        root_node = None
        try:
            # CPU Intensive Unzip
            root_node = await self.zip_processor.process_zip_in_pool(str(temp_file_path), file.filename, output_dir=str(self.temp_dir))
            
            # I/O Bound Uploads
            uploaded_map = await self.upload_manager.upload_files_recursive(root_node, client_id)
            
            self.db.commit()
            
            root_key = root_node.path
            root_doc_id = root_node.document_link_id or "UNKNOWN"
            
            contents_map = {k: v for k, v in uploaded_map.items() if k != root_key}
            total_unzipped_size = sum(int(f.file_size) for f in contents_map.values())
            
            unzip_detail = UnzipDetail(
                document_link_id=root_doc_id,
                client_id=client_id,
                file_name=file.filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_unzipped_size),
                tree_struct=self.zip_processor.build_simple_tree(root_node),
                files_unzipped=contents_map
            )
            
            response = {root_doc_id: unzip_detail}
            await self._cache_response(response, root_doc_id, client_id)
            return response
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self.zip_processor.cleanup_extracted_files(root_node)

    async def process_direct_upload_parallel(self, file: UploadFile, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Entries point for direct file upload (Parallel Processing):
        """
        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{file.filename}"
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)

        root_node = None
        try:
            # Unzip locally to PVC
            root_node = await self.zip_processor.process_zip_in_pool(str(temp_file_path), file.filename, output_dir=str(self.pvc_dir))
            
            # Collect paths
            pvc_paths = []
            await self.zip_processor.collect_pvc_paths(root_node, pvc_paths)
            if not pvc_paths:
                await logger.awarning("No files extracted from zip")
                return {}

            # Call File Handler Service
            relative_files_map = {os.path.basename(p): p for p in pvc_paths}
            payload = list(relative_files_map.keys())
            
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.post(settings.FILE_HANDLER_SERVICE_URL, json=payload, timeout=600.0)
                    resp.raise_for_status()
                    result_data = resp.json() 
                except Exception as e:
                    await logger.aerror(f"File Handler Service failed: {e}")
                    raise HTTPException(status_code=502, detail=f"File Handler Service error: {str(e)}")

            if "error" in result_data and result_data["error"]:
                 await logger.awarning(f"Some files failed to upload: {result_data.get('error_log')}")

            # Process Results
            upload_results = {}
            for res_filename, doc_id in result_data.items():
                if res_filename in ["error", "error_log"]: 
                    continue
                abs_path = relative_files_map.get(res_filename)
                if abs_path:
                    upload_results[abs_path] = {"document_link_id": doc_id}
            
            files_unzipped_map = {}
            total_size = [0] 

            # Internal helper for mapping results
            async def _map_results(node):
                if node.temp_path in upload_results:
                    res = upload_results[node.temp_path]
                    doc_id = res.get('document_link_id', 'UNKNOWN')
                    f_size = res.get('size', node.size)
                    
                    node.document_link_id = doc_id
                    total_size[0] += int(f_size)
                    
                    db_entry = KycDocumentUnzip(
                        client_id=client_id,
                        document_link_id=doc_id,
                        document_name=node.name,
                        file_type="file",
                        parent_doc_link_id="UNKNOWN_DIRECT_UPLOAD", 
                        document_path=node.temp_path,
                        file_size=int(float(f_size)) if f_size else 0,
                        is_extracted="Y",
                        ver_num=settings.VER_NUM
                    )
                    self.db.add(db_entry)
                    
                    files_unzipped_map[node.path] = UnzippedFileDetail(
                        file_name=node.name,
                        document_link_id=doc_id,
                        file_size=str(f_size)
                    )

                if node.children:
                    for child in node.children:
                         await _map_results(child)
            
            await _map_results(root_node)
            self.db.commit()
            
            root_doc_id = "UNKNOWN" 
            
            unzip_detail = UnzipDetail(
                document_link_id=root_doc_id,
                client_id=client_id,
                file_name=file.filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_size[0]),
                tree_struct=self.zip_processor.build_simple_tree(root_node),
                files_unzipped=files_unzipped_map
            )
            
            response = {root_doc_id: unzip_detail}
            await self._cache_response(response, root_doc_id, client_id)
            return response
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self.zip_processor.cleanup_extracted_files(root_node)

    async def process_direct_upload_optimized(self, file: UploadFile, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Entry point for direct file upload (Optimized/Concurrent):
        """
        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{file.filename}"
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)

        root_node = None
        try:
            root_node = await self.zip_processor.process_zip_in_pool(str(temp_file_path), file.filename, output_dir=str(self.temp_dir))
            
            # Upload extracted files using Concurrent Manager
            db_records = []
            uploaded_map = await self.upload_manager.upload_files_concurrently(root_node, client_id, db_records)
            
            if db_records:
                self.db.add_all(db_records)
                self.db.commit()
                
            # Extract root info
            root_key = root_node.path
            root_doc_id = root_node.document_link_id or "UNKNOWN"
            
            contents_map = {k: v for k, v in uploaded_map.items() if k != root_key}
            total_unzipped_size = sum(int(f.file_size) for f in contents_map.values())
            
            unzip_detail = UnzipDetail(
                document_link_id=root_doc_id,
                client_id=client_id,
                file_name=file.filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_unzipped_size),
                tree_struct=self.zip_processor.build_simple_tree(root_node),
                files_unzipped=contents_map
            )
            
            response = {root_doc_id: unzip_detail}
            await self._cache_response(response, root_doc_id, client_id)
            return response

        finally:
             if temp_file_path.exists():
                os.remove(temp_file_path)
             if root_node:
                self.zip_processor.cleanup_extracted_files(root_node)

    async def process_document_unzip(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """Entry point for existing document."""
        # Check cache
        stmt = select(KycDocumentUnzip).where(
            KycDocumentUnzip.document_link_id == document_link_id,
            KycDocumentUnzip.client_id == client_id
        ).order_by(KycDocumentUnzip.create_dt.desc())
        existing = self.db.execute(stmt).scalars().all()
        if settings.UNZIP_ENABLE_CACHE and existing:
            cached_resp = await self._build_response_from_cache(existing, document_link_id, client_id)
            if cached_resp:
                return cached_resp
        
        # Fetch
        filename, content = await self.doc_client.fetch_document(document_link_id)

        # Log Parent Zip Record
        parent_record = KycDocumentUnzip(
            client_id=client_id,
            document_link_id=document_link_id,
            document_name=filename,
            file_type="zip",
            parent_doc_link_id=None,
            document_path="DOCUMENTUM_FETCHED",
            is_extracted="Y",
            ver_num=settings.VER_NUM
        )
        self.db.add(parent_record)
        self.db.commit()
        
        # Save temp
        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{filename}"
        async with aiofiles.open(temp_file_path, 'wb') as f:
            await f.write(content)
            
        root_node = None
        try:
            root_node = await self.zip_processor.process_zip_in_pool(str(temp_file_path), filename, output_dir=str(self.temp_dir))
            
            uploaded_map = await self.upload_manager.upload_files_recursive(root_node, client_id, document_link_id)
            self.db.commit()
            
            root_key = root_node.path
            contents_map = {k: v for k, v in uploaded_map.items() if k != root_key}
            total_unzipped_size = sum(int(f.file_size) for f in contents_map.values())
            
            unzip_detail = UnzipDetail(
                document_link_id=document_link_id,
                client_id=client_id,
                file_name=filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_unzipped_size),
                tree_struct=self.zip_processor.build_simple_tree(root_node),
                files_unzipped=contents_map
            )
            response = {document_link_id: unzip_detail}
            await self._cache_response(response, document_link_id, client_id)
            return response
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self.zip_processor.cleanup_extracted_files(root_node)

    async def process_document_unzip_optimized(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """Entry point for existing document (Optimized)."""
        # Check cache
        stmt = select(KycDocumentUnzip).where(
            KycDocumentUnzip.document_link_id == document_link_id,
            KycDocumentUnzip.client_id == client_id
        ).order_by(KycDocumentUnzip.create_dt.desc())
        existing = self.db.execute(stmt).scalars().all()
        if settings.UNZIP_ENABLE_CACHE and existing:
            cached_resp = await self._build_response_from_cache(existing, document_link_id, client_id)
            if cached_resp:
                return cached_resp
            
        # Fetch
        filename, content = await self.doc_client.fetch_document(document_link_id)
        
        # Log Parent Zip Record
        parent_record = KycDocumentUnzip(
            client_id=client_id,
            document_link_id=document_link_id,
            document_name=filename,
            file_type="zip",
            parent_doc_link_id=None,
            document_path="DOCUMENTUM_FETCHED",
            is_extracted="Y",
            ver_num=settings.VER_NUM
        )
        self.db.add(parent_record)
        self.db.commit()

        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{filename}"
        async with aiofiles.open(temp_file_path, 'wb') as f:
            await f.write(content)
            
        root_node = None
        try:
            root_node = await self.zip_processor.process_zip_in_pool(str(temp_file_path), filename, output_dir=str(self.temp_dir))
            
            # Root is already in Documentum (we fetched it)
            # Use concurrent upload for children
            db_records = []
            uploaded_map = {}
            uploaded_map[root_node.path] = UnzippedFileDetail(
                file_name=filename, document_link_id=document_link_id, file_size=str(root_node.size)
            )
            
            if root_node.children:
                sem = asyncio.Semaphore(settings.DOCUMENTUM_MAX_CONNECTIONS)
                tasks = [
                    self.upload_manager.upload_files_concurrently(child, client_id, db_records, document_link_id, sem)
                    for child in root_node.children
                ]
                child_results = await asyncio.gather(*tasks)
                for res in child_results:
                    uploaded_map.update(res)
            
            if db_records:
                self.db.add_all(db_records)
                self.db.commit()
                
            root_key = root_node.path
            contents_map = {k: v for k, v in uploaded_map.items() if k != root_key}
            total_unzipped_size = sum(int(f.file_size) for f in contents_map.values())
            
            unzip_detail = UnzipDetail(
                document_link_id=document_link_id,
                client_id=client_id,
                file_name=filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_unzipped_size),
                tree_struct=self.zip_processor.build_simple_tree(root_node),
                files_unzipped=contents_map
            )
            response = {document_link_id: unzip_detail}
            await self._cache_response(response, document_link_id, client_id)
            return response
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self.zip_processor.cleanup_extracted_files(root_node)
                
    async def process_document_unzip_parallel(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """Parallel Unzip with File Handler."""
        # Check cache
        stmt = select(KycDocumentUnzip).where(
            KycDocumentUnzip.document_link_id == document_link_id,
            KycDocumentUnzip.client_id == client_id
        ).order_by(KycDocumentUnzip.create_dt.desc())
        existing = self.db.execute(stmt).scalars().all()
        if settings.UNZIP_ENABLE_CACHE and existing:
            cached_resp = await self._build_response_from_cache(existing, document_link_id, client_id)
            if cached_resp:
                return cached_resp

        # Fetch
        filename, content = await self.doc_client.fetch_document(document_link_id)

        # Log Parent Zip Record
        parent_record = KycDocumentUnzip(
            client_id=client_id,
            document_link_id=document_link_id,
            document_name=filename,
            file_type="zip",
            parent_doc_link_id=None,
            document_path="DOCUMENTUM_FETCHED",
            is_extracted="Y",
            ver_num=settings.VER_NUM
        )
        self.db.add(parent_record)
        self.db.commit()
        
        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{filename}"
        async with aiofiles.open(temp_file_path, 'wb') as f:
            await f.write(content)

        root_node = None
        try:
            # Unzip to PVC
            root_node = await self.zip_processor.process_zip_in_pool(str(temp_file_path), filename, output_dir=str(self.pvc_dir))
            
            pvc_paths = []
            await self.zip_processor.collect_pvc_paths(root_node, pvc_paths)
            if not pvc_paths:
                return {} 

            # File Handler
            relative_files_map = {os.path.basename(p): p for p in pvc_paths}
            payload = list(relative_files_map.keys())
            
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.post(settings.FILE_HANDLER_SERVICE_URL, json=payload, timeout=600.0)
                    resp.raise_for_status()
                    result_data = resp.json() 
                except Exception as e:
                    await logger.aerror(f"File Handler Service failed: {e}")
                    raise HTTPException(status_code=502, detail=f"File Handler Service error: {str(e)}")

            if "error" in result_data and result_data["error"]:
                 await logger.awarning(f"Some files failed to upload: {result_data.get('error_log')}")

            upload_results = {}
            for res_filename, doc_id in result_data.items():
                if res_filename in ["error", "error_log"]: 
                    continue
                abs_path = relative_files_map.get(res_filename)
                if abs_path:
                    upload_results[abs_path] = {"document_link_id": doc_id}

            files_unzipped_map = {}
            total_size = [0]

            async def _map_results(node):
                if node.temp_path in upload_results:
                    res = upload_results[node.temp_path]
                    doc_id = res.get('document_link_id', 'UNKNOWN')
                    f_size = res.get('size', node.size)
                    
                    node.document_link_id = doc_id
                    total_size[0] += int(f_size)
                    
                    db_entry = KycDocumentUnzip(
                        client_id=client_id,
                        document_link_id=doc_id,
                        document_name=node.name,
                        file_type="file",
                        parent_doc_link_id=document_link_id,
                        document_path=node.temp_path,
                        file_size=int(float(f_size)) if f_size else 0,
                        is_extracted="Y",
                        ver_num=settings.VER_NUM
                    )
                    self.db.add(db_entry)
                    files_unzipped_map[node.path] = UnzippedFileDetail(
                        file_name=node.name, document_link_id=doc_id, file_size=str(f_size)
                    )

                if node.children:
                    for child in node.children:
                         await _map_results(child)
            
            await _map_results(root_node)
            self.db.commit()
            
            unzip_detail = UnzipDetail(
                document_link_id=document_link_id,
                client_id=client_id,
                file_name=filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_unzipped_size),
                tree_struct=self.zip_processor.build_simple_tree(root_node),
                files_unzipped=files_unzipped_map
            )
            
            response = {document_link_id: unzip_detail}
            await self._cache_response(response, document_link_id, client_id)
            return response
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self.zip_processor.cleanup_extracted_files(root_node)

async def get_workflow_service(
    db: Session = Depends(get_db),
    doc_client: DocumentumClient = Depends(get_documentum_client)
) -> UnzipWorkflowService:
    return UnzipWorkflowService(db, doc_client)
