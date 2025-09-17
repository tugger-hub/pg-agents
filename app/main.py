import contextlib

import psycopg
from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from app.config import get_settings
from app.webhook import router as webhook_router


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage the lifespan of the application, including the database connection pool.
    """
    settings = get_settings()
    # On startup, create the connection pool and attach it to the app state
    pool = ConnectionPool(
        conninfo=settings.database_url,
        min_size=2,
        max_size=settings.db_pool_size,
    )
    app.state.db_pool = pool
    yield
    # On shutdown, close the connection pool
    app.state.db_pool.close()


app = FastAPI(
    title="PG Solo Lite API",
    description="API for handling webhooks and other external integrations.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
def read_root():
    """
    Root endpoint for health checks.
    """
    return {"message": "PG Solo Lite API is running."}


# Include the webhook router
app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])
