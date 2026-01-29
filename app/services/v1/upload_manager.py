"""
Upload Manager Service.
Handles the upload of extracted files to Documentum.
Supports both sequential (recursive) and concurrent upload strategies.
"""
import asyncio
from pathlib import Path
from typing import Dict, List
import aiofiles

from sqlalchemy.orm import Session
from app.core.v1.config import AppSettings
from app.db.v1.schema import KycDocumentUnzip
from app.documentum.v1.client import DocumentumClient
from app.models.v1.unzip import UnzippedFileDetail, ZipNode
from app.core.v1.logging import get_logger

logger = get_logger(__name__)
settings = AppSettings()

class UploadManager:
    def __init__(self, db: Session, doc_client: DocumentumClient):
        self.db = db
        self.doc_client = doc_client

    async def upload_files_concurrently(self, node: ZipNode, client_id: str, db_records: List[KycDocumentUnzip], parent_doc_id: str = None, semaphore: asyncio.Semaphore = None) -> Dict[str, UnzippedFileDetail]:
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
                        file_type="zip" if node.is_archive else "file",
                        parent_doc_link_id=parent_doc_id,
                        document_path=str(file_path),
                        file_size=node.size,
                        is_extracted="Y",
                        ver_num=settings.VER_NUM
                        # status field removed, success implied by absence of error in reserved_field1
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
                    
                    # Log Error to DB
                    db_entry = KycDocumentUnzip(
                        client_id=client_id,
                        document_name=node.name,
                        document_link_id="ERROR", 
                        file_type="zip" if node.is_archive else "file",
                        parent_doc_link_id=parent_doc_id,
                        document_path=str(file_path),
                        reserved_field1=str(e)[:4000],
                        is_extracted="N",
                        ver_num=settings.VER_NUM
                    )
                    db_records.append(db_entry)
            else:
                 await logger.awarning(f"File not found at {file_path}")

        # 2. Process Children (Concurrent)
        if node.children:
             # If we uploaded self (e.g. Nested Zip), children belong to us.
             # If we are a directory (not uploaded), children belong to OUR parent.
             pass_parent_id = current_node_doc_id if current_node_doc_id else parent_doc_id
             
             tasks = [
                 self.upload_files_concurrently(child, client_id, db_records, pass_parent_id, semaphore)
                 for child in node.children
             ]
             
             if tasks:
                 results = await asyncio.gather(*tasks)
                 for child_map in results:
                     uploaded_files_map.update(child_map)

        return uploaded_files_map

    async def upload_files_recursive(self, node: ZipNode, client_id: str, parent_doc_id: str = None) -> Dict[str, UnzippedFileDetail]:
        """
        Recursively uploads extracted files to Documentum and updates DB directly (Serial/Sync DB used in loop).
        Note: Ideally this should also be refactored to use aggregation, but keeping as 'Serial' legacy behavior.
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
                        file_type="zip" if node.is_archive else "file",
                        parent_doc_link_id=parent_doc_id,
                        document_path=str(file_path),
                        file_size=node.size,
                        is_extracted="Y",
                        ver_num=settings.VER_NUM
                    )
                    self.db.add(db_entry)
                    # Note: We are not committing here, transaction is managed by caller usually, but kept serial behavior pattern
                    
                    uploaded_files_map[node.path] = UnzippedFileDetail(
                        file_name=node.name,
                        document_link_id=doc_id,
                        file_size=str(node.size)
                    )
                    
                    # If it's a nested zip, we recurse into its children
                    if node.children: 
                        for child in node.children:
                            child_map = await self.upload_files_recursive(child, client_id, doc_id)
                            uploaded_files_map.update(child_map)
                            
                except Exception as e:
                    await logger.aerror(f"Failed to upload {node.name}: {e}")
                    node.error = f"Upload failed: {e}"
                    
                    # Log Error to DB
                    db_entry = KycDocumentUnzip(
                        client_id=client_id,
                        document_name=node.name,
                        document_link_id="ERROR",
                        file_type="zip" if node.is_archive else "file",
                        parent_doc_link_id=parent_doc_id,
                        document_path=str(file_path),
                        reserved_field1=str(e)[:4000],
                        is_extracted="N",
                        ver_num=settings.VER_NUM
                    )
                    self.db.add(db_entry)
            else:
                await logger.awarning(f"File not found at {file_path}")
                
        elif node.is_archive and node.children:
             # It's the root archive or a pure container
             for child in node.children:
                 child_map = await self.upload_files_recursive(child, client_id, parent_doc_id)
                 uploaded_files_map.update(child_map)

        return uploaded_files_map
