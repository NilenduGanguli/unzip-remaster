from sqlalchemy import Column, String, Boolean, Date, DateTime, Text, Integer, Float
from pydantic import BaseModel, Field
from datetime import date, time, datetime
import uuid
from app.db.v1.engine import Base

# --- SQLAlchemy Models ---

class KycDocumentUnzip(Base):
    __tablename__ = "kyc_document_unzip"

    kyc_document_unzip_id = Column("KYC_DOCUMENT_UNZIP_ID", String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    kyc_document_id = Column("KYC_DOCUMENT_ID", String(36), nullable=True)
    document_component_state = Column("DOCUMENT_COMPONENT_STATE", String(36), nullable=True)
    document_link_id = Column("DOCUMENT_LINK_ID", String(50), nullable=True)
    document_name = Column("DOCUMENT_NAME", String(4000), nullable=True)
    document_path = Column("DOCUMENT_PATH", String(4000), nullable=True)
    document_s3_path = Column("DOCUMENT_S3_PATH", String(4000), nullable=True)
    file_type = Column("FILE_TYPE", String(256), nullable=True)
    file_size = Column("FILE_SIZE", Integer, nullable=True)
    contains_zip_child = Column("CONTAINS_ZIP_CHILD", String(2), nullable=True)
    
    # Ancestors
    ancestor_l1 = Column("ANCESTOR_L1", String(4000), nullable=True)
    ancestor_l2 = Column("ANCESTOR_L2", String(4000), nullable=True)
    ancestor_l3 = Column("ANCESTOR_L3", String(4000), nullable=True)
    ancestor_l4 = Column("ANCESTOR_L4", String(4000), nullable=True)
    
    uploaded_by = Column("UPLOADED_BY", String(256), nullable=True)
    is_classified = Column("IS_CLASSIFIED", String(2), nullable=True)
    is_extracted = Column("IS_EXTRACTED", String(2), nullable=True)
    classification_name = Column("CLASSIFICATION_NAME", String(4000), nullable=True)
    
    # Flags
    s0_flag = Column("S0_FLAG", String(2), nullable=True)
    s1_flag = Column("S1_FLAG", String(2), nullable=True)
    
    batch_id = Column("BATCH_ID", String(25), nullable=True)
    batch_dt = Column("BATCH_DT", Date, nullable=True)
    batch_status = Column("BATCH_STATUS", String(256), nullable=True)
    
    create_id = Column("CREATE_ID", String(25), nullable=True)
    create_dt = Column("CREATE_DT", Date, default=datetime.now().date)
    lst_upd_id = Column("LST_UPD_ID", String(25), nullable=True)
    lst_upd_dt = Column("LST_UPD_DT", Date, default=datetime.now().date)
    ver_num = Column("VER_NUM", Integer, nullable=True)
    act_strt_dt = Column("ACT_STRT_DT", Date, nullable=True)
    act_end_dt = Column("ACT_END_DT", Date, nullable=True)
    kyc_shard_num = Column("KYC_SHARD_NUM", Integer, nullable=True)
    lst_upd_time = Column("LST_UPD_TIME", Integer, nullable=True) # Changed from DateTime to Number per script
    
    # Reserved Fields (Used for Logging)
    reserved_field1 = Column("RESERVED_FIELD1", String(4000), nullable=True) # Error Log
    reserved_field2 = Column("RESERVED_FIELD2", String(4000), nullable=True) # Request Log
    reserved_field3 = Column("RESERVED_FIELD3", String(4000), nullable=True)
    
    unzip_uploaded_kyc_doc_id = Column("UNZIP_UPLOADED_KYC_DOC_ID", String(36), nullable=True)
    parent_doc_link_id = Column("PARENT_DOC_LINK_ID", String(50), nullable=True)
    unzip_doc_link_id = Column("UNZIP_DOC_LINK_ID", String(50), nullable=True)
    
    client_id = Column("CLIENT_ID", String(30), nullable=True)
    core_country = Column("CORE_COUNTRY", String(2), nullable=True)
    core_region = Column("CORE_REGION", String(30), nullable=True)
    
    name_rcvd_from_documentum = Column("NAME_RCVD_FROM_DOCUMENTUM", String(4000), nullable=True)
    component_id = Column("COMPONENT_ID", String(36), nullable=True)
    component_type = Column("COMPONENT_TYPE", String(20), nullable=True)
