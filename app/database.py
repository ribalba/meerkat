from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

# check_same_thread=False is required for SQLite when used across FastAPI's threadpool.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    # Import models so they are registered on Base before create_all.
    from . import models  # noqa: F401

    # Fresh deploys only: the models define the full schema (including the BigInteger
    # `position` columns), so create_all() produces everything in one shot. There is no
    # incremental-migration step because we never carry an older on-disk schema forward.
    Base.metadata.create_all(bind=engine)
