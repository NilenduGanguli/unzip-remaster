# from app_process.database import Base
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


# --- Pydantic Models ---

class UnzippedFileDetail(BaseModel):
    file_name: str
    document_link_id: str
    file_size: str

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
    document_link_id: str = Field(..., alias="document_link_id")
    client_id: str = Field(..., alias="client_id")
    file_name: str = Field(..., alias="file_name")
    zipped_size: str = Field(..., alias="zipped_size")
    unzipped_size: str = Field(..., alias="unzipped_size")
    tree_struct: Dict[str, Any] = Field(..., alias="tree_struct")
    files_unzipped: Dict[str, UnzippedFileDetail] = Field(..., alias="files_unzipped")

    class Config:
        populate_by_name = True