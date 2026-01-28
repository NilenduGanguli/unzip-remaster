from sqlalchemy import Column, String, Boolean, Date, DateTime, Text
from app_process.database import Base
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import uuid
from datetime import date, time, datetime

# --- SQLAlchemy Models ---

class KycDocumentUnzip(Base):
    __tablename__ = "kyc_document_unzip"

    kyc_unzip_id = Column("KYC_UNZIP_ID", String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id = Column("CLIENT_ID", String(255))
    document_link_id = Column("DOCUMENT_LINK_ID", String(255), nullable=False)
    document_name = Column("DOCUMENT_NAME", String(255))
    document_type = Column("DOCUMENT_TYPE", String(100))
    parent_document_link_id = Column("PARENT_DOCUMENT_LINK_ID", String(255))
    lst_upd_time = Column("LST_UPD_TIME", DateTime, default=datetime.now)
    lst_upd_dt = Column("LST_UPD_DT", Date, default=datetime.now().date)
    document_path = Column("DOCUMENT_PATH", Text) # Using Text for CLOB/Large path
    status = Column("STATUS", Boolean)
    error = Column("ERROR", String(3000))

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
    pvc_files: List[str] = Field(default=[], alias="pvc_files") # Added field for PVC files list

    class Config:
        populate_by_name = True
