from sqlalchemy import Column, String, Boolean, Date, DateTime, Text
from pydantic import BaseModel, Field
from datetime import date, time, datetime
import uuid
from app.db.v1.engine import Base

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