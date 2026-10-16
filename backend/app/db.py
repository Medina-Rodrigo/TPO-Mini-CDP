"""
Database connection setup, shared by the API,
the importer, and the tests
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Copy backend/.env into environment variables (local dev only;
# on Railway the variable are set int he dashboard instead)
load_dotenv()

# os.environ[...] (not .get) crashed immediately if the setting is missing
# better to fail at start than to fail later unknowingly
DATABASE_URL = os.environ["DATABASE_URL"]

# Hosts hand out URLs starting with "postgres://" or "postgresql://"
# SQLAlchemy needs to know which driver to use, rewrote prefix
# to "postgresql+psycopg://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# the engine manages a pool of connections to the database
engine = create_engine(DATABASE_URL)

# SessionLocal() hands out a "session": one unit of work (reads + writes)
# that we commit all at once or roll back if anything fails
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    """
    Every table class inherits from this
    so SQLAlchemy can find them all
    """