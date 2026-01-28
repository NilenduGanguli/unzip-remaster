import asyncio
import os
import shutil
import zipfile
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from concurrent.futures import ProcessPoolExecutor

import aiofiles
import httpx
from fastapi import UploadFile, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.v1.config import AppSettings
from app.db.v1.engine import get_db
from app.db.v1.schema import KycDocumentUnzip
from app.documentum.v1.client import DocumentumClient, get_documentum_client
from app.models.v1.unzip import (
    UnzipDetail, UnzippedFileDetail, ZipNode
)
from app.core.v1.logging import get_logger

logger = get_logger(__name__)
settings = AppSettings()

# --- Worker Function (Must be top-level) ---

def unzip_worker_task(zip_path_str: str, output_dir_str: str, original_name: str, relative_path: str = "") -> ZipNode:
    """
    Standard top-level function for ProcessPoolExecutor.
    
    This function performs recursive unzipping of a zip file. It is CPU-bound and designed 
    to be run in a separate process to avoid blocking the asyncio event loop.
    
    Args:
        zip_path_str (str): Absolute path to the zip file to extract.
        output_dir_str (str): Directory where extracted files will be saved.
        original_name (str): The name of the zip file being processed.
        relative_path (str): The relative path within the zip structure (used for recursion).
        
    Returns:
        ZipNode: A tree structure representing the contents of the zip file, including
                 nested zips and extracted files.
    """
    zip_path = Path(zip_path_str)
    output_dir = Path(output_dir_str)
    
    # Root node for this specific zip archive
    node = ZipNode(
        name=original_name,
        path=relative_path if relative_path else original_name,
        size=zip_path.stat().st_size if zip_path.exists() else 0,
        is_archive=True,
        temp_path=zip_path_str
    )

    try:
        if not zipfile.is_zipfile(zip_path):
             node.error = "Invalid or corrupted zip file"
             return node

        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Calculate total compressed size for metadata
            node.compressed_size = sum(i.compress_size for i in zf.infolist())
            
            for info in zf.infolist():
                entry_name = info.filename
                # Clean logical name to avoid directory traversal issues
                clean_name = os.path.basename(entry_name.rstrip('/'))
                if not clean_name: continue # Skip empty path segments
                
                # Logical path in the virtual tree structure
                current_rel_path = f"{node.path}/{clean_name}"
                
                if info.is_dir():
                    node.children.append(ZipNode(
                        name=clean_name,
                        path=current_rel_path,
                        is_directory=True
                    ))
                    continue
                
                # It's a file - Perform Extraction
                # Use uuid to prevent filename collisions in the flat PVC structure
                unique_name = f"{uuid.uuid4()}_{clean_name}"
                target_path = output_dir / unique_name
                
                try:
                    # Extract file stream directly to target
                    with zf.open(info) as source, open(target_path, "wb") as target:
                        shutil.copyfileobj(source, target)
                    
                    extracted_size = target_path.stat().st_size
                    
                    if entry_name.lower().endswith('.zip'):
                        # Nested Zip Discovered: Recurse
                        # We call the worker task recursively (synchronously within this process)
                        # to handle the nested zip structure.
                        child_node = unzip_worker_task(
                            str(target_path),
                            output_dir_str,
                            clean_name,
                            current_rel_path
                        )
                        # Add link id placeholder for post-processing
                        # child_node.document_link_id = "PENDING_UPLOAD"
                        node.children.append(child_node)
                    else:
                        # Standard extracted file
                        node.children.append(ZipNode(
                            name=clean_name,
                            path=current_rel_path,
                            size=extracted_size,
                            temp_path=str(target_path) 
                        ))
                except Exception as e:
                    logger.error(f"Failed to extract {entry_name}: {e}")
                    node.children.append(ZipNode(
                        name=clean_name,
                        path=current_rel_path,
                        error=str(e)
                    ))
                    
    except Exception as e:
        node.error = f"Zip processing failed: {e}"
        
    return node

class UnzipWorkflowService:
    def __init__(self, db: Session, doc_client: DocumentumClient):
        self.db = db
        self.doc_client = doc_client
        self.pvc_dir = Path(settings.PVC_DIR)
        self.temp_dir = Path(settings.TEMP_DIR)
        
        # Ensure directories exist
        self.pvc_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _build_simple_tree(self, node: ZipNode) -> Dict[str, Any]:
        """Convert ZipNode tree to simplified structure: {name: {children...}}"""
        children_dict = {}
        if node.children:
            for child in node.children:
                child_tree = self._build_simple_tree(child)
                children_dict.update(child_tree)
        return {node.name: children_dict}

    def _cleanup_extracted_files(self, node: ZipNode):
        """Recursively remove extracted files."""
        if node.children:
            for child in node.children:
                self._cleanup_extracted_files(child)

        # Cleanup the file represented by this node (whether file or zip archive)
        # For the root node, this duplicates the clean up in finally block, but that's safe.
        if node.temp_path:
             path = Path(node.temp_path)
             if path.exists():
                 try:
                     os.remove(path)
                 except Exception as e:
                     logger.warning(f"Failed to cleanup {path}: {e}")

    async def _upload_files_concurrently(self, node: ZipNode, client_id: str, db_records: List[KycDocumentUnzip], parent_doc_id: str = None, semaphore: asyncio.Semaphore = None) -> Dict[str, UnzippedFileDetail]:
        """
        Recursively uploads extracted files to Documentum Concurrenty.
        Aggregates DB records into db_records list for deferred batch insertion.
        """
        if semaphore is None:
            # Initialize semaphore with limit from settings
            semaphore = asyncio.Semaphore(settings.DOCUMENTUM_MAX_CONNECTIONS)

        uploaded_files_map = {}
        current_node_doc_id = None
        
        # 1. Upload Self
        if node.temp_path and not node.is_directory:
            file_path = Path(node.temp_path)
            
            if file_path.exists():
                try:
                    async with semaphore:
                        # Upload to Documentum
                        async with aiofiles.open(file_path, 'rb') as f:
                            content = await f.read()
                            
                        doc_id = await self.doc_client.upload_document(
                            content, 
                            node.name, 
                            parent_doc_id
                        )
                    
                    current_node_doc_id = doc_id
                    node.document_link_id = doc_id
                    
                    # Record in List (Deferred DB Insert)
                    db_entry = KycDocumentUnzip(
                        client_id=client_id,
                        document_link_id=doc_id,
                        document_name=node.name,
                        document_type="zip" if node.is_archive else "file",
                        parent_document_link_id=parent_doc_id,
                        document_path=str(file_path),
                        status=True
                    )
                    db_records.append(db_entry)
                    
                    uploaded_files_map[node.path] = UnzippedFileDetail(
                        file_name=node.name,
                        document_link_id=doc_id,
                        file_size=str(node.size)
                    )

                except Exception as e:
                    await logger.aerror(f"Failed to upload {node.name}: {e}")
                    node.error = f"Upload failed: {e}"
            else:
                 await logger.awarning(f"File not found at {file_path}")

        # 2. Process Children (Concurrent)
        if node.children:
             # If we uploaded self (e.g. Nested Zip), children belong to us.
             # If we are a directory (not uploaded), children belong to OUR parent.
             pass_parent_id = current_node_doc_id if current_node_doc_id else parent_doc_id
             
             tasks = [
                 self._upload_files_concurrently(child, client_id, db_records, pass_parent_id, semaphore)
                 for child in node.children
             ]
             
             if tasks:
                 results = await asyncio.gather(*tasks)
                 for child_map in results:
                     uploaded_files_map.update(child_map)

        return uploaded_files_map

    async def _build_response_from_cache(self, existing: List[KycDocumentUnzip], document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """Reconstruct the UnzipDetail response from DB records."""
        # Note: We can only reconstruct flat structure as DB may not store full hierarchy logic
        # And size info might be missing if we don't query disk.
        
        files_map = {}
        total_size = 0
        names = []
        
        for record in existing:
            # Try to get size from disk if available
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
            file_name="CACHED_RESULT", # We don't have original filename unless we query parent or store it
            zipped_size="0", # Unknown
            unzipped_size=str(total_size),
            tree_struct=tree_struct,
            files_unzipped=files_map
        )
        await logger.ainfo(f"Returning cached result for {document_link_id}")
        return {document_link_id: unzip_detail}

    async def _process_zip_in_pool(self, zip_path: str, filename: str, output_dir: Optional[str] = None) -> ZipNode:
        """Runs the CPU-bound unzip worker in a separate process."""
        target_dir = output_dir if output_dir else str(self.pvc_dir)
        loop = asyncio.get_running_loop()
        try:
             with ProcessPoolExecutor(max_workers=settings.UNZIP_MAX_WORKERS) as pool:
                result_node = await loop.run_in_executor(
                    pool,
                    unzip_worker_task,
                    zip_path,
                    target_dir,
                    filename
                )
                return result_node
        except Exception as e:
            await logger.aerror(f"Process Pool Error: {e}")
            raise

    async def _upload_files_recursive(self, node: ZipNode, client_id: str, parent_doc_id: str = None) -> Dict[str, UnzippedFileDetail]:
        """
        Recursively uploads extracted files to Documentum and updates DB.
        Returns mapped by logical path: { "path/to/file": FileDetail }
        """
        uploaded_files_map = {}
        # If this node represents a file (or nested zip archive itself) that has been extracted
        if node.temp_path and not node.is_directory:
            file_path = Path(node.temp_path)
            
            if file_path.exists():
                try:
                    # Upload to Documentum
                    async with aiofiles.open(file_path, 'rb') as f:
                        content = await f.read()
                        
                    doc_id = await self.doc_client.upload_document(
                        content, 
                        node.name, 
                        parent_doc_id
                    )
                    
                    node.document_link_id = doc_id
                    
                    # Record in DB
                    db_entry = KycDocumentUnzip(
                        client_id=client_id,
                        document_link_id=doc_id,
                        document_name=node.name,
                        document_type="zip" if node.is_archive else "file",
                        parent_document_link_id=parent_doc_id,
                        document_path=str(file_path), # We store the PVC path
                        status=True
                    )
                    self.db.add(db_entry)
                    
                    uploaded_files_map[node.path] = UnzippedFileDetail(
                        file_name=node.name,
                        document_link_id=doc_id,
                        file_size=str(node.size)
                    )
                    
                    # If it's a nested zip, we recurse into its children
                    if node.children: 
                        for child in node.children:
                            child_map = await self._upload_files_recursive(child, client_id, doc_id)
                            uploaded_files_map.update(child_map)
                            
                except Exception as e:
                    await logger.aerror(f"Failed to upload {node.name}: {e}")
                    node.error = f"Upload failed: {e}"
            else:
                await logger.awarning(f"File not found at {file_path}")
                
        elif node.is_archive and node.children:
             # It's the root archive or a pure container
             for child in node.children:
                 child_map = await self._upload_files_recursive(child, client_id, parent_doc_id)
                 uploaded_files_map.update(child_map)

        return uploaded_files_map

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
            # CPU Inteisve Unzip - Store in TEMP_DIR for synchronous processing
            root_node = await self._process_zip_in_pool(str(temp_file_path), file.filename, output_dir=str(self.temp_dir))
            
            # I/O Bound Uploads
            uploaded_map = await self._upload_files_recursive(root_node, client_id)
            
            self.db.commit()
            
            root_key = root_node.path
            root_doc_id = root_node.document_link_id or "UNKNOWN"
            
            # Filter map for contents (exclude the root zip itself from list of unzipped files)
            contents_map = {k: v for k, v in uploaded_map.items() if k != root_key}
            
            total_unzipped_size = sum(int(f.file_size) for f in contents_map.values())
            
            unzip_detail = UnzipDetail(
                document_link_id=root_doc_id,
                client_id=client_id,
                file_name=file.filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_unzipped_size),
                tree_struct=self._build_simple_tree(root_node),
                files_unzipped=contents_map
            )
            
            return {root_doc_id: unzip_detail}
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self._cleanup_extracted_files(root_node)

    async def process_direct_upload_parallel(self, file: UploadFile, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Entry point for direct file upload (Parallel Processing):
        1. Save upload to temp
        2. Unzip to PVC
        3. Send list of files to File Handler Service
        4. Integrate results
        """
        # Save uploaded file
        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{file.filename}"
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
            
        root_node = None
        try:
            # Unzip locally to PVC - Explicitly use PVC_DIR for parallel processing
            root_node = await self._process_zip_in_pool(str(temp_file_path), file.filename, output_dir=str(self.pvc_dir))
            
            # Collect paths
            pvc_paths = []
            await self._collect_pvc_paths(root_node, pvc_paths)
            if not pvc_paths:
                await logger.awarning("No files extracted from zip")
                return {} # Or empty structure

            # Call File Handler Service
            handler_url = settings.FILE_HANDLER_SERVICE_URL
            
            # Prepare payload: List of filenames relative to the shared volume root
            # pvc_paths contains absolute paths like /app/unzip-pvc-data/UUID_filename
            relative_files_map = {os.path.basename(p): p for p in pvc_paths}
            payload = list(relative_files_map.keys())
            
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.post(handler_url, json=payload, timeout=600.0)
                    resp.raise_for_status()
                    result_data = resp.json() 
                except Exception as e:
                    await logger.aerror(f"File Handler Service failed: {e}")
                    raise HTTPException(status_code=502, detail=f"File Handler Service error: {str(e)}")

            # Check for partial errors
            if "error" in result_data and result_data["error"]:
                 await logger.awarning(f"Some files failed to upload: {result_data.get('error_log')}")

            # Process Results
            # Map absolute_path -> details for _map_results
            upload_results = {}
            for res_filename, doc_id in result_data.items():
                if res_filename in ["error", "error_log"]: 
                    continue
                
                # Map back to absolute path
                abs_path = relative_files_map.get(res_filename)
                if abs_path:
                    upload_results[abs_path] = {"document_link_id": doc_id}
            
            files_unzipped_map = {}
            total_size_unzipped = 0

            # Recursive helper to build response map by walking the tree and matching with upload results
            async def _map_results(node: ZipNode, current_map: Dict[str, UnzippedFileDetail]):
                nonlocal total_size_unzipped
                
                # Check if this node corresponds to an uploaded file
                if node.temp_path in upload_results:
                    res = upload_results[node.temp_path]
                    doc_id = res.get('document_link_id', 'UNKNOWN')
                    f_size = res.get('size', node.size) # Use returned size or node size
                    
                    node.document_link_id = doc_id
                    total_size_unzipped += int(f_size)
                    
                    db_entry = KycDocumentUnzip(
                        client_id=client_id,
                        document_link_id=doc_id,
                        document_name=node.name,
                        document_type="file",
                        parent_document_link_id="UNKNOWN_DIRECT_UPLOAD", 
                        document_path=node.temp_path,
                        status=True
                    )
                    self.db.add(db_entry)
                    
                    current_map[node.path] = UnzippedFileDetail(
                        file_name=node.name,
                        document_link_id=doc_id,
                        file_size=str(f_size)
                    )

                if node.children:
                    for child in node.children:
                         await _map_results(child, current_map)
            
            await _map_results(root_node, files_unzipped_map)
            self.db.commit()
            
            # Since we don't have a parent ID from documentum, use a placeholder or check if one was returned (unlikely for direct upload)
            root_doc_id = "UNKNOWN" 
            
            unzip_detail = UnzipDetail(
                document_link_id=root_doc_id, # Maybe generate one or use UNKNOWN
                client_id=client_id,
                file_name=file.filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_size_unzipped),
                tree_struct=self._build_simple_tree(root_node),
                files_unzipped=files_unzipped_map
            )
            
            return {root_doc_id: unzip_detail}
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self._cleanup_extracted_files(root_node)

    async def process_direct_upload_optimized(self, file: UploadFile, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Entry point for direct file upload (Optimized/Concurrent):
        """
        # Save uploaded file
        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{file.filename}"
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
            
        root_node = None
        try:
            # CPU Inteisve Unzip - Store in TEMP_DIR for synchronous processing
            root_node = await self._process_zip_in_pool(str(temp_file_path), file.filename, output_dir=str(self.temp_dir))
            
            # 1. Upload Root File to establish Parent Record
            root_doc_id = "UNKNOWN"
            if root_node.temp_path:
                path = Path(root_node.temp_path)
                if path.exists():
                    async with aiofiles.open(path, 'rb') as f:
                        f_content = await f.read()
                    
                    # Upload root zip
                    root_doc_id = await self.doc_client.upload_document(f_content, root_node.name, None)
                    root_node.document_link_id = root_doc_id
                    
                    # DB Transaction 1: Create Parent Record
                    parent_record = KycDocumentUnzip(
                        client_id=client_id,
                        document_link_id=root_doc_id,
                        document_name=root_node.name,
                        document_type="zip",
                        parent_document_link_id=None,
                        document_path=str(path),
                        status=True
                    )
                    self.db.add(parent_record)
                    self.db.commit()
            
            # 2. Optimized Concurrent Uploads for Children
            db_records = []
            uploaded_map = {}
            
            # Add root to map manually since we uploaded it separately
            uploaded_map[root_node.path] = UnzippedFileDetail(
                file_name=root_node.name,
                document_link_id=root_doc_id,
                file_size=str(root_node.size)
            )

            if root_node.children:
                # Initialize semaphore
                sem = asyncio.Semaphore(settings.DOCUMENTUM_MAX_CONNECTIONS)
                
                tasks = [
                    self._upload_files_concurrently(child, client_id, db_records, root_doc_id, sem)
                    for child in root_node.children
                ]
                
                child_results = await asyncio.gather(*tasks)
                for res in child_results:
                    uploaded_map.update(res)
            
            # DB Transaction 2: Bulk Insert Children
            if db_records:
                self.db.add_all(db_records)
                self.db.commit()
            
            root_key = root_node.path
            
            # Filter map for contents (exclude the root zip itself from list of unzipped files)
            contents_map = {k: v for k, v in uploaded_map.items() if k != root_key}
            
            total_unzipped_size = sum(int(f.file_size) for f in contents_map.values())
            
            unzip_detail = UnzipDetail(
                document_link_id=root_doc_id,
                client_id=client_id,
                file_name=file.filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_unzipped_size),
                tree_struct=self._build_simple_tree(root_node),
                files_unzipped=contents_map
            )
            
            return {root_doc_id: unzip_detail}
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self._cleanup_extracted_files(root_node)

    async def process_document_unzip_optimized(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Entry point for existing document (Optimized/Concurrent):
        """
        # Check if already processed
        stmt = select(KycDocumentUnzip).where(
            KycDocumentUnzip.document_link_id == document_link_id
        )
        result = self.db.execute(stmt)
        existing = result.scalars().all()
        
        if settings.UNZIP_ENABLE_CACHE and existing:
            return await self._build_response_from_cache(existing, document_link_id, client_id)
        
        # Fetch
        filename, content = await self.doc_client.fetch_document(document_link_id)
        
        # DB Transaction 1: Create Parent Record (The Zip File itself)
        # We perform this after fetch ensures it exists/is accessible
        parent_record = KycDocumentUnzip(
            client_id=client_id,
            document_link_id=document_link_id,
            document_name=filename,
            document_type="zip",
            parent_document_link_id=None,
            document_path="DOCUMENTUM_FETCHED", # We don't have a persistent local path
            status=True
        )
        self.db.add(parent_record)
        self.db.commit()

        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{filename}"
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            await out_file.write(content)
            
        root_node = None
        try:
            # Unzip - Store in TEMP_DIR for synchronous processing as requested
            root_node = await self._process_zip_in_pool(str(temp_file_path), filename, output_dir=str(self.temp_dir))
            
            # Optimized Concurrent Uploads
            db_records = []
            uploaded_map = {}
            
            # Root is already in Documentum (we fetched it)
            uploaded_map[root_node.path] = UnzippedFileDetail(
                file_name=filename,
                document_link_id=document_link_id,
                file_size=str(root_node.size)
            )

            if root_node.children:
                # Initialize semaphore
                sem = asyncio.Semaphore(settings.DOCUMENTUM_MAX_CONNECTIONS)
                
                tasks = [
                    self._upload_files_concurrently(child, client_id, db_records, document_link_id, sem)
                    for child in root_node.children
                ]
                
                child_results = await asyncio.gather(*tasks)
                for res in child_results:
                    uploaded_map.update(res)

            # DB Transaction 2: Bulk Insert Children
            if db_records:
                self.db.add_all(db_records)
                self.db.commit()
            
            root_key = root_node.path
            root_doc_id = document_link_id
            
            contents_map = {k: v for k, v in uploaded_map.items() if k != root_key}
            total_unzipped_size = sum(int(f.file_size) for f in contents_map.values())

            unzip_detail = UnzipDetail(
                document_link_id=root_doc_id,
                client_id=client_id,
                file_name=filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_unzipped_size),
                tree_struct=self._build_simple_tree(root_node),
                files_unzipped=contents_map
            )
            
            return {root_doc_id: unzip_detail}
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self._cleanup_extracted_files(root_node)

    async def process_document_unzip(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Entry point for existing document:
        1. Fetch from Documentum
        2. Unzip
        3. Upload extracted parts
        4. Commit DB
        """
        # Check if already processed
        stmt = select(KycDocumentUnzip).where(
            KycDocumentUnzip.document_link_id == document_link_id
        )
        result = self.db.execute(stmt)
        existing = result.scalars().all()
        
        if settings.UNZIP_ENABLE_CACHE and existing:
            return await self._build_response_from_cache(existing, document_link_id, client_id)
        
        # Fetch
        filename, content = await self.doc_client.fetch_document(document_link_id)
        
        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{filename}"
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            await out_file.write(content)
            
        root_node = None
        try:
            # Unzip - Store in TEMP_DIR for synchronous processing as requested
            root_node = await self._process_zip_in_pool(str(temp_file_path), filename, output_dir=str(self.temp_dir))
            
            # Upload extracted (Child of the original document_link_id)
            uploaded_map = await self._upload_files_recursive(root_node, client_id, document_link_id)
            
            self.db.commit()
            
            root_key = root_node.path
            # For process_document_unzip, the input document_link_id IS the root id.
            # But root_node.document_link_id might also be set if we re-uploaded it?
            # _upload_files_recursive uploads root if temp_path exists.
            # Here we fetched it to temp_path, passing it to _process_zip_in_pool, so root_node has temp_path.
            # So _upload_files_recursive WILL upload it again to Documentum as a new version or new doc?
            # The logic in _upload_files_recursive calls doc_client.upload_document.
            # If we want to avoid re-uploading the ROOT document (since we just fetched it from there),
            # we should probably prevent that. But assuming current logic is desired:
            
            # Wait, if we fetch "000000000d", we don't want to create "000000000x" which is a copy of it.
            # But let's stick to existing behavior logic but just fix response format.
            # The user request example shows response key "000000000d".
            
            root_doc_id = document_link_id
            
            contents_map = {k: v for k, v in uploaded_map.items() if k != root_key}
            total_unzipped_size = sum(int(f.file_size) for f in contents_map.values())

            unzip_detail = UnzipDetail(
                document_link_id=root_doc_id,
                client_id=client_id,
                file_name=filename,
                zipped_size=str(root_node.size),
                unzipped_size=str(total_unzipped_size),
                tree_struct=self._build_simple_tree(root_node),
                files_unzipped=contents_map
            )
            
            return {root_doc_id: unzip_detail}
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self._cleanup_extracted_files(root_node)

    async def _collect_pvc_paths(self, node: ZipNode, file_list: List[str]):
        """Recursively collect file paths from ZipNode that are extracted files."""
        if node.temp_path and not node.is_directory and not node.is_archive:
            file_list.append(node.temp_path)
        
        # If it's a directory or archive with children
        if node.children:
            for child in node.children:
                await self._collect_pvc_paths(child, file_list)

    async def process_document_unzip_parallel(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Parallel Unzip:
        1. Fetch
        2. Unzip
        3. Send list of files to File Handler Service
        4. Integrate results
        """
        # Check if already processed
        stmt = select(KycDocumentUnzip).where(
            KycDocumentUnzip.document_link_id == document_link_id
        )
        result = self.db.execute(stmt)
        existing = result.scalars().all()

        if settings.UNZIP_ENABLE_CACHE and existing:
            return await self._build_response_from_cache(existing, document_link_id, client_id)

        # Fetch
        filename, content = await self.doc_client.fetch_document(document_link_id)
        
        temp_file_path = self.temp_dir / f"{uuid.uuid4()}_{filename}"
        async with aiofiles.open(temp_file_path, 'wb') as out_file:
            await out_file.write(content)
            
        root_node = None
        try:
            # Unzip locally to PVC - Explicitly use PVC_DIR for parallel processing
            root_node = await self._process_zip_in_pool(str(temp_file_path), filename, output_dir=str(self.pvc_dir))
            
            # Collect paths
            pvc_paths = []
            await self._collect_pvc_paths(root_node, pvc_paths)
            if not pvc_paths:
                await logger.awarning("No files extracted from zip")
                return {} # Or empty structure

            # Call File Handler Service
            handler_url = settings.FILE_HANDLER_SERVICE_URL
            
            # Prepare payload: List of filenames relative to the shared volume root
            # pvc_paths contains absolute paths like /app/unzip-pvc-data/UUID_filename
            relative_files_map = {os.path.basename(p): p for p in pvc_paths}
            payload = list(relative_files_map.keys())
            
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.post(handler_url, json=payload, timeout=600.0)
                    resp.raise_for_status()
                    result_data = resp.json() 
                    # Expecting: {"filename1": "doc_id1", "filename2": "doc_id2", "error": [...]}
                except Exception as e:
                    await logger.aerror(f"File Handler Service failed: {e}")
                    raise HTTPException(status_code=502, detail=f"File Handler Service error: {str(e)}")

            # Check for partial errors
            if "error" in result_data and result_data["error"]:
                 await logger.awarning(f"Some files failed to upload: {result_data.get('error_log')}")

            # Process Results
            # Map absolute_path -> details for _map_results
            upload_results = {}
            for res_filename, doc_id in result_data.items():
                if res_filename in ["error", "error_log"]: 
                    continue
                
                # Map back to absolute path
                abs_path = relative_files_map.get(res_filename)
                if abs_path:
                    upload_results[abs_path] = {"document_link_id": doc_id}
            
            files_unzipped_map = {}
            total_size_unzipped = 0

            # Recursive helper to build response map by walking the tree and matching with upload results
            async def _map_results(node: ZipNode, current_map: Dict[str, UnzippedFileDetail]):
                nonlocal total_size_unzipped
                
                # Check if this node corresponds to an uploaded file
                if node.temp_path in upload_results:
                    res = upload_results[node.temp_path]
                    doc_id = res.get('document_link_id', 'UNKNOWN')
                    f_size = res.get('size', node.size) # Use returned size or node size
                    
                    node.document_link_id = doc_id
                    total_size_unzipped += int(f_size)
                    
                    # Store DB entry (If file handler didn't do it, or duplicate it? 
                    # Assuming file Handler handles upload, but maybe WE handle DB? 
                    # The prompt says "integrated in the response". Usually separate service implies it handles its own logic.
                    # But if we need to show it in OUR db for tracking?
                    # Let's assume WE record the unzip event here using the returned IDs.
                    
                    db_entry = KycDocumentUnzip(
                        client_id=client_id,
                        document_link_id=doc_id,
                        document_name=node.name,
                        document_type="file",
                        parent_document_link_id=document_link_id, # Simplified parent link
                        document_path=node.temp_path,
                        status=True
                    )
                    self.db.add(db_entry)
                    
                    current_map[node.path] = UnzippedFileDetail(
                        file_name=node.name,
                        document_link_id=doc_id,
                        file_size=str(f_size)
                    )

                if node.children:
                    for child in node.children:
                         await _map_results(child, current_map)
            
            await _map_results(root_node, files_unzipped_map)
            self.db.commit()
            
            unzip_detail = UnzipDetail(
                document_link_id=document_link_id,
                client_id=client_id,
                file_name=filename, # Ensure this uses the original filename from Documentum fetch
                zipped_size=str(root_node.size),
                unzipped_size=str(total_size_unzipped),
                tree_struct=self._build_simple_tree(root_node),
                files_unzipped=files_unzipped_map
            )
            
            return {document_link_id: unzip_detail}
            
        finally:
            if temp_file_path.exists():
                os.remove(temp_file_path)
            if root_node:
                self._cleanup_extracted_files(root_node)

async def get_workflow_service(
    db: Session = Depends(get_db),
    doc_client: DocumentumClient = Depends(get_documentum_client)
) -> UnzipWorkflowService:
    return UnzipWorkflowService(db, doc_client)
