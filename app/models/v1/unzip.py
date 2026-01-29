"""
Pydantic Models for Unzip Service.
Defines the data structures used for API responses and internal data passing.
- UnzipDetail: The main response structure
- ZipNode: Represents a file or folder in the zip structure
"""
# from app_process.database import Base
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


# --- Pydantic Models ---

class UnzippedFileDetail(BaseModel):
    file_name: str = Field(..., alias="file_name")
    document_link_id: str = Field(..., alias="file_id")
    file_size: str = Field(..., alias="file_size")

    class Config:
        populate_by_name = True

class ZipNode(BaseModel):
    name: str = ""
    path: str = ""
    compressed_size: int = 0
    size: int = 0
    children: List['ZipNode'] = []
    is_directory: bool = False
    is_archive: bool = False
    document_link_id: Optional[str] = None
    error: Optional[str] = None
    temp_path: Optional[str] = Field(default=None, exclude=True) # Internal use only
    
    # Avoid recursion issues in Pydantic V2
    model_config = {
        "populate_by_name": True
    }

class UnzipDetail(BaseModel):
    document_link_id: str = Field(..., alias="doc_id")
    client_id: str = Field(..., alias="client_id")
    file_name: str = Field(..., alias="file_name")
    zipped_size: str = Field(..., alias="zipped_size")
    unzipped_size: str = Field(..., alias="unzipped_size")
    tree_struct: Dict[str, Any] = Field(..., alias="tree_struct")
    files_unzipped: Dict[str, UnzippedFileDetail] = Field(..., alias="files_unzipped")

    class Config:
        populate_by_name = True