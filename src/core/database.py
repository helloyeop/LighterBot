from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from contextlib import asynccontextmanager
import structlog
import os
from src.models.database import Base

logger = structlog.get_logger()


class DatabaseManager:
    def __init__(self):
        self.engine = None
        self.async_session = None
        # SQLite database in data directory
        self.db_path = "data/lighter_trading.db"

    async def connect(self):
        try:
            # Create data directory if it doesn't exist
            os.makedirs("data", exist_ok=True)

            # SQLite connection string for async
            database_url = f"sqlite+aiosqlite:///{self.db_path}"

            self.engine = create_async_engine(
                database_url,
                echo=False,
                connect_args={"check_same_thread": False}
            )

            self.async_session = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

            # Create tables if they don't exist
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            logger.info("Database connected successfully", path=self.db_path)

        except Exception as e:
            logger.error("Failed to connect to database", error=str(e))
            raise

    async def disconnect(self):
        if self.engine:
            await self.engine.dispose()
            logger.info("Database disconnected")

    @asynccontextmanager
    async def get_session(self):
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def health_check(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error("Database health check failed", error=str(e))
            return False


# Global database manager instance
db_manager = DatabaseManager()


# Dependency for FastAPI
async def get_db():
    async with db_manager.get_session() as session:
        yield session