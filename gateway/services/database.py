import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


DB_USER = os.getenv("POSTGRES_USER", "callcenterai")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "ChangeThisNow_!")
DB_NAME = os.getenv("POSTGRES_DB", "callcenterai")
DB_HOST = os.getenv("POSTGRES_HOST", "postgres")  # service name from compose
DB_PORT = os.getenv("POSTGRES_PORT", "5432")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
