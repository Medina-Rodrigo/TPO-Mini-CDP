"""
Create any missing tables. Run with:

python -m app.create_tables

"""
from app import models
from app.db import Base, engine

if __name__ == "__main__":
    # create_all only creates tables that don't exist yet
    # safe to run repeatedly
    Base.metadata.create_all(engine)
    print("Tables ready:", ", ".join(Base.metadata.tables))
    