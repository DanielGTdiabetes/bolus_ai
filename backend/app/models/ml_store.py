from sqlalchemy import Column, String, LargeBinary, DateTime
from sqlalchemy.sql import func
from app.core.db import Base

class MLModelStore(Base):
    __tablename__ = "ml_models_store"

    model_name = Column(String, primary_key=True, index=True)  # Ej: "catboost_residual_30m_p50"
    user_id = Column(String, primary_key=True, index=True)     # Ej: "admin"
    model_data = Column(LargeBinary, nullable=False)           # El archivo .cbm en binario
    version = Column(String, nullable=True)                    # Hash o timestamp para control
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
