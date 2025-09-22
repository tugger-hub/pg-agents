"""
Database connection and session management.

This module sets up the SQLAlchemy engine, session maker, and the declarative
base for ORM models.
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from .config import settings

# Ensure the database URL is compatible with psycopg v3
db_url = str(settings.database_url)
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

# Create the SQLAlchemy engine using the database URL from settings
engine = create_engine(
    db_url,
    pool_size=settings.db_pool_size,
    pool_pre_ping=True
)

# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a base class for our models to inherit from
Base = declarative_base()
