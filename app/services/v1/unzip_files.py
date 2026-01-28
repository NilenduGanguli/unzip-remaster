
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
from app.core.v1.logging import get_logger

logger = get_logger(__name__)
settings = AppSettings()

class UnzipWorkflowService:
    def __init__(self, db: Session, doc_client: DocumentumClient):
        self.db = db
        self.doc_client = doc_client
        self.pvc_dir = Path(settings.PVC_DIR)
        self.temp_dir = Path(settings.TEMP_DIR)
        
        self.zip_processor = ZipProcessor()
        self.upload_manager = UploadManager(db, doc_client)
        
        # Ensure directories exist
        self.pvc_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def _build_response_from_cache(self, existing: List[KycDocumentUnzip], document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """Reconstruct the UnzipDetail response from DB records."""
        files_map = {}
        total_size = 0
        names = []
        
        for record in existing:
            f_size = "0"
            if record.document_path and os.path.exists(record.document_path):
                 try:
                     f_size = str(os.path.getsize(record.document_path))
                 except: pass
            
            total_size += int(f_size)
            files_map[record.document_name] = UnzippedFileDetail(
                file_name=record.document_name,
                document_link_id=record.document_link_id,
                file_size=f_size
            )
            names.append(record.document_name)

        # Approximate tree (Flat)
        tree_struct = {document_link_id: {name: {} for name in names}}

        unzip_detail = UnzipDetail(
            document_link_id=document_link_id,
            client_id=client_id,
            file_name="CACHED_RESULT",
            zipped_size="0",
            unzipped_size=str(total_size),
            tree_struct=tree_struct,
            files_unzipped=files_map
        )
        await logger.ainfo(f"Returning cached result for {document_link_id}")
        return {document_link_id: unzip_detail}

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
            
            return {root_doc_id: unzip_detail}
            
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
            
            return {root_doc_id: unzip_detail}
            
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
            
            return {root_doc_id: unzip_detail}

        finally:
             if temp_file_path.exists():
                os.remove(temp_file_path)
             if root_node:
                self.zip_processor.cleanup_extracted_files(root_node)

    async def process_document_unzip(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """Entry point for existing document."""
        # Check cache
        stmt = select(KycDocumentUnzip).where(KycDocumentUnzip.document_link_id == document_link_id)
        existing = self.db.execute(stmt).scalars().all()
        if settings.UNZIP_ENABLE_CACHE and existing:
            return await self._build_response_from_cache(existing, document_link_id, client_id)
        
        # Fetch
        filename, content = await self.doc_client.fetch_document(document_link_id)
        
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
            return {document_link_id: unzip_detail}
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self.zip_processor.cleanup_extracted_files(root_node)

    async def process_document_unzip_optimized(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """Entry point for existing document (Optimized)."""
        # Check cache
        stmt = select(KycDocumentUnzip).where(KycDocumentUnzip.document_link_id == document_link_id)
        existing = self.db.execute(stmt).scalars().all()
        if settings.UNZIP_ENABLE_CACHE and existing:
            return await self._build_response_from_cache(existing, document_link_id, client_id)
            
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
            return {document_link_id: unzip_detail}
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self.zip_processor.cleanup_extracted_files(root_node)
                
    async def process_document_unzip_parallel(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """Parallel Unzip with File Handler."""
        # Check cache
        stmt = select(KycDocumentUnzip).where(KycDocumentUnzip.document_link_id == document_link_id)
        existing = self.db.execute(stmt).scalars().all()
        if settings.UNZIP_ENABLE_CACHE and existing:
            return await self._build_response_from_cache(existing, document_link_id, client_id)

        # Fetch
        filename, content = await self.doc_client.fetch_document(document_link_id)
        
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
            
            return {document_link_id: unzip_detail}
            
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
