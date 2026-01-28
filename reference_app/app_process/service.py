import asyncio
import os
import shutil
import zipfile
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ProcessPoolExecutor

import aiofiles
from fastapi import UploadFile, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app_process.database import settings, get_db
from app_process.documentum_client import DocumentumClient, get_documentum_client
from app_process.models import (
    KycDocumentUnzip, UnzipDetail, UnzippedFileDetail, ZipNode
)

logger = logging.getLogger(__name__)

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
                        node.children.append(child_node)
                    else:
                        # Standard File: Add to tree with temp path reference
                        node.children.append(ZipNode(
                            name=clean_name,
                            path=current_rel_path,
                            size=extracted_size,
                            compressed_size=info.compress_size,
                            temp_path=str(target_path)
                        ))
                        
                except Exception as e:
                    node.children.append(ZipNode(
                        name=clean_name,
                        path=current_rel_path,
                        error=f"Extraction failed: {str(e)}"
                    ))

    except Exception as e:
        node.error = f"Zip processing error: {str(e)}"
        
    return node

# --- Services (Stage-wise Dependencies) ---

class KycRepository:
    """
    Repository pattern for handling database interactions related to KYC Document Logs.
    Abstracts direct SQL/ORM calls from the business logic.
    """
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def create_log(self, client_id: str, document_link_id: str, document_name: str) -> KycDocumentUnzip:
        """Creates the initial log entry for a document processing request."""
        record = KycDocumentUnzip(
            client_id=client_id,
            document_link_id=document_link_id,
            document_name=document_name,
            lst_upd_dt=datetime.now().date(),
            lst_upd_time=datetime.now()
        )
        self.db.add(record)
        await self.db.commit()
        return record

    async def update_log(self, record: KycDocumentUnzip, node: ZipNode, status: bool, error: str = None):
        """Updates the main log entry with final status and error details."""
        record.document_name = node.name
        record.document_path = node.path
        record.status = status
        record.error = error
        record.lst_upd_dt = datetime.now().date()
        await self.db.commit()
    
    async def log_child(self, client_id: str, doc_id: str, name: str, path: str, parent_id: str, status: bool, error: str = None):
        """Logs an individual extracted file (child document)."""
        rec = KycDocumentUnzip(
             client_id=client_id,
             document_link_id=doc_id,
             document_name=name,
             document_path=path,
             parent_document_link_id=parent_id,
             status=status,
             error=error
        )
        self.db.add(rec)
        await self.db.commit()

class UnzipProcessor:
    """
    Service responsible for CPU-intensive zip extraction.
    Uses a ProcessPoolExecutor to avoid blocking the main AsyncIO event loop.
    """
    def __init__(self):
        # Initialize a pool of worker processes. 
        # Default behavior uses os.cpu_count() workers.
        self.process_pool = ProcessPoolExecutor() 

    async def unzip_archive(self, zip_path: Path, output_dir: Path, original_name: str) -> ZipNode:
        """
        Offloads the unzipping task to a separate process.
        Returns when the entire directory structure is processed.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.process_pool,
            unzip_worker_task,
            str(zip_path),
            str(output_dir),
            original_name,
            ""
        )
        
    def shutdown(self):
        """Cleanly shuts down the process pool."""
        self.process_pool.shutdown()

class TreeUploader:
    pass 

# --- Workflow Service ---

class UnzipWorkflowService:
    """
    Orchestrator service that ties together database logging, zip processing, 
    and documentum uploads. Implements the core business logic.
    """
    def __init__(
        self, 
        repo: KycRepository, 
        processor: UnzipProcessor, 
        doc_client: DocumentumClient
    ):
        self.repo = repo
        self.processor = processor
        self.doc_client = doc_client
        self.upload_semaphore = asyncio.Semaphore(settings.UNZIP_UPLOAD_THREADS)
    
    async def process_direct_upload(self, file: UploadFile, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Handles the flow for a direct file upload from the API client.
        1. Saves stream to PVC.
        2. Uploads raw zip to Documentum.
        3. Logs to DB.
        4. Unzips content via Processor.
        5. Uploads all extracted files recursively.
        6. Updates DB and returns response.
        """
        logger.info(f"Workflow: process_direct_upload for {client_id}")
        
        req_id = str(uuid.uuid4())
        pvc_req_dir = Path(settings.PVC_DIR) / req_id
        pvc_req_dir.mkdir(parents=True, exist_ok=True)
        
        kyc_record = None
        
        try:
            # 1. Save to PVC (Buffering input stream)
            safe_filename = os.path.basename(file.filename) or "upload.zip"
            main_zip_path = pvc_req_dir / safe_filename
            async with aiofiles.open(main_zip_path, 'wb') as f:
                while chunk := await file.read(1024 * 1024):
                    await f.write(chunk)
            total_size = main_zip_path.stat().st_size
            
            # 2. Upload Root Zip to Documentum
            async with aiofiles.open(main_zip_path, 'rb') as f:
                content = await f.read()
            doc_id = await self.doc_client.upload_document(content, safe_filename)
            
            # 3. Log Initial Request
            kyc_record = await self.repo.create_log(client_id, doc_id, safe_filename)
            
            # 4. Unzip (CPU Bound Operation)
            root_node = await self.processor.unzip_archive(main_zip_path, pvc_req_dir, safe_filename)
            root_node.document_link_id = doc_id
            
            # 5. Upload Children (I/O Bound Operation)
            pvc_file_list = []
            await self._upload_tree_recursive(root_node, doc_id, client_id, pvc_file_list)
            
            # 6. Update Final Log with Status
            error_msg = root_node.error[:3000] if root_node.error else None
            status = not bool(root_node.error)
            await self.repo.update_log(kyc_record, root_node, status, error_msg)
            
            # 7. Construct Response Structure
            return self._build_response(doc_id, client_id, root_node, total_size, pvc_file_list)

        except Exception as e:
            logger.error(f"Workflow failed: {e}", exc_info=True)
            if kyc_record:
                await self.repo.update_log(kyc_record, ZipNode(name=safe_filename), False, str(e)[:3000])
            raise e

    async def process_document_unzip(self, document_link_id: str, client_id: str) -> Dict[str, UnzipDetail]:
        """
        Handles the flow for processing an existing document in Documentum.
        1. Fetches document from Documentum.
        2. Steps 3-7 same as process_direct_upload.
        """
        logger.info(f"Workflow: process_document_unzip for {client_id}")
        
        req_id = str(uuid.uuid4())
        pvc_req_dir = Path(settings.PVC_DIR) / req_id
        pvc_req_dir.mkdir(parents=True, exist_ok=True)
        
        kyc_record = None

        try:
            # 1. Fetch from Documentum
            filename, content = await self.doc_client.fetch_document(document_link_id)
            safe_filename = filename
            main_zip_path = pvc_req_dir / safe_filename
            async with aiofiles.open(main_zip_path, 'wb') as f:
                await f.write(content)
            total_size = len(content)
            
            # 2. Log Initial Request
            kyc_record = await self.repo.create_log(client_id, document_link_id, safe_filename)
            
            # 3. Unzip
            root_node = await self.processor.unzip_archive(main_zip_path, pvc_req_dir, safe_filename)
            root_node.document_link_id = document_link_id
            
            # 4. Upload Children
            pvc_file_list = []
            await self._upload_tree_recursive(root_node, document_link_id, client_id, pvc_file_list)
            
            # 5. Update Log
            error_msg = root_node.error[:3000] if root_node.error else None
            status = not bool(root_node.error)
            await self.repo.update_log(kyc_record, root_node, status, error_msg)
            
            # 6. Response
            return self._build_response(document_link_id, client_id, root_node, total_size, pvc_file_list)

        except Exception as e:
            logger.error(f"Workflow failed: {e}", exc_info=True)
            if kyc_record:
                await self.repo.update_log(kyc_record, ZipNode(name=safe_filename), False, str(e)[:3000])
            raise e


    async def _upload_tree_recursive(self, node: ZipNode, parent_id: str, client_id: str, pvc_list: List[str]):
        """
        Recursively uploads extracted files to Documentum.
        
        - Uses asyncio.gather for parallel uploads of children at the same level.
        - Uses a Semaphore to limit concurrent upload tasks.
        - Creates ephemeral DB sessions for logging child documents to avoid 
          conflicts in the main session.
        """
        if node.temp_path:
            pvc_list.append(node.temp_path)
            
            # Upload only if it's a file that hasn't been uploaded (no ID) and has no errors
            if not node.document_link_id and not node.error:
                async with self.upload_semaphore:
                    try:
                        async with aiofiles.open(node.temp_path, 'rb') as f:
                            content = await f.read()
                        
                        doc_id = await self.doc_client.upload_document(content, node.name, parent_id)
                        node.document_link_id = doc_id
                        
                        # Use a separate ephemeral session for this log to safely run in asyncio.gather
                        # Main session cannot be shared across tasks safely
                        from app_process.database import AsyncSessionLocal
                        async with AsyncSessionLocal() as task_db:
                             task_repo = KycRepository(task_db)
                             await task_repo.log_child(client_id, doc_id, node.name, node.path, parent_id, True)

                    except Exception as e:
                        node.error = f"Upload failed: {e}"
                        # Log error state
                        from app_process.database import AsyncSessionLocal
                        async with AsyncSessionLocal() as task_db:
                             task_repo = KycRepository(task_db)
                             await task_repo.log_child(client_id, "ERROR", node.name, node.path, parent_id, False, str(e)[:3000])

        if node.children:
            # Determine the parent ID for the next level:
            # If current node is an archive (nested zip), its ID becomes the parent for its contents.
            # Otherwise, pass the current parent_id down.
            next_parent = node.document_link_id if (node.is_archive and node.document_link_id) else parent_id
            
            # Parallelize processing of children
            tasks = [
                self._upload_tree_recursive(child, next_parent, client_id, pvc_list)
                for child in node.children
            ]
            if tasks:
                await asyncio.gather(*tasks)

    def _build_response(self, doc_id, client_id, root_node, total_size, pvc_list):
        children_map = self._build_children_map(root_node)
        unzipped_map = {}
        self._populate_files_unzipped(root_node, unzipped_map)
        
        return {
            doc_id: UnzipDetail(
                document_link_id=doc_id,
                client_id=client_id,
                file_name=root_node.name,
                zipped_size=str(total_size // 1024),
                unzipped_size=str(self._sum_node_sizes(root_node) // 1024),
                tree_struct={root_node.name: children_map},
                files_unzipped=unzipped_map,
                pvc_files=pvc_list
            )
        }

    @staticmethod
    def _build_children_map(node: ZipNode) -> Dict:
        children = {}
        for child in node.children:
            if child.is_directory or child.is_archive:
                c_map = UnzipWorkflowService._build_children_map(child)
                if child.error:
                    c_map["error"] = child.error
                children[child.name] = c_map
            else:
                f_info = {
                    "type": "file",
                    "size": child.size,
                    "id": child.document_link_id
                }
                if child.error:
                    f_info["error"] = child.error
                children[child.name] = f_info
        return children

    @staticmethod
    def _populate_files_unzipped(node: ZipNode, container: Dict[str, UnzippedFileDetail]):
        if not node.is_directory and not node.is_archive and node.document_link_id:
             kb_size = str(max(1, node.size // 1024))
             container[node.name] = UnzippedFileDetail(
                 file_name=node.name,
                 document_link_id=node.document_link_id,
                 file_size=kb_size
             )
        for child in node.children:
            UnzipWorkflowService._populate_files_unzipped(child, container)

    @staticmethod
    def _sum_node_sizes(node: ZipNode) -> int:
        total = 0
        if not node.is_directory and not node.is_archive:
            total += node.size
        for child in node.children:
            total += UnzipWorkflowService._sum_node_sizes(child)
        return total


# --- Dependency Providers ---

_unzip_processor = UnzipProcessor()

def get_kyc_repository(db: AsyncSession = Depends(get_db)) -> KycRepository:
    return KycRepository(db)

def get_unzip_processor() -> UnzipProcessor:
    return _unzip_processor

def get_workflow_service(
    repo: KycRepository = Depends(get_kyc_repository),
    processor: UnzipProcessor = Depends(get_unzip_processor),
    doc_client: DocumentumClient = Depends(get_documentum_client)
) -> UnzipWorkflowService:
    return UnzipWorkflowService(repo, processor, doc_client)