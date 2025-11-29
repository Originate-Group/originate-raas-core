"""Database connection and session management for RaaS Core."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from .config import get_settings

settings = get_settings()

# Create database engine
# Conservative pool settings for local development
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,          # Verify connections before using
    pool_size=5,                 # Base pool of 5 connections
    max_overflow=10,             # Allow up to 15 total connections
    pool_recycle=3600,           # Recycle connections every hour
    pool_timeout=30,             # Timeout after 30 seconds
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency function to get database session.

    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
