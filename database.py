from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base

engine = create_engine("sqlite:///./smartcube.db", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Condominio(Base):
    __tablename__ = "condominios"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String)
    cnpj = Column(String)
    boxes = Column(Integer)
    mensalidade = Column(Float)

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True)
    senha_hash = Column(String)
    is_admin = Column(Boolean, default=True)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()