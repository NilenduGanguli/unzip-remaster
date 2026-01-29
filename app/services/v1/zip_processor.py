"""
Zip Processing Utility.
Handles the extraction of zip files using a ProcessPoolExecutor to avoid blocking the main event loop.
Supports recursive unzipping and structure building.
"""
import asyncio
import os
import uuid
import shutil
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional, List
from concurrent.futures import ProcessPoolExecutor

from app.core.v1.config import AppSettings
from app.models.v1.unzip import ZipNode
from app.core.v1.logging import get_logger

logger = get_logger(__name__)
settings = AppSettings()

def unzip_worker_task(zip_path_str: str, output_dir_str: str, original_name: str, relative_path: str = "") -> ZipNode:
    """
    Standard top-level function for ProcessPoolExecutor.
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
                        child_node = unzip_worker_task(
                            str(target_path),
                            output_dir_str,
                            clean_name,
                            current_rel_path
                        )
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

class ZipProcessor:
    def __init__(self):
        self.pvc_dir = Path(settings.PVC_DIR)
        self.temp_dir = Path(settings.TEMP_DIR)
        
        # Ensure directories exist
        self.pvc_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def process_zip_in_pool(self, zip_path: str, filename: str, output_dir: Optional[str] = None) -> ZipNode:
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

    def build_simple_tree(self, node: ZipNode) -> Dict[str, Any]:
        """Convert ZipNode tree to simplified structure: {name: {children...}}"""
        children_dict = {}
        if node.children:
            for child in node.children:
                child_tree = self.build_simple_tree(child)
                children_dict.update(child_tree)
        return {node.name: children_dict}

    def cleanup_extracted_files(self, node: ZipNode):
        """Recursively remove extracted files."""
        if node.children:
            for child in node.children:
                self.cleanup_extracted_files(child)

        if node.temp_path:
             path = Path(node.temp_path)
             if path.exists():
                 try:
                     os.remove(path)
                 except Exception as e:
                     logger.warning(f"Failed to cleanup {path}: {e}")

    async def collect_pvc_paths(self, node: ZipNode, file_list: List[str]):
        """Recursively collect file paths from ZipNode that are extracted files."""
        if node.temp_path and not node.is_directory and not node.is_archive:
            file_list.append(node.temp_path)
        
        if node.children:
            for child in node.children:
                await self.collect_pvc_paths(child, file_list)
