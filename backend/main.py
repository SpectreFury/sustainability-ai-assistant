import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.answers import router as answers_router
from routers.auth import router as auth_router
from routers.documents import router as documents_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    task_broker = None
    if os.getenv("REDIS_URL"):
        from broker import broker

        task_broker = broker
        await task_broker.startup()

    try:
        yield
    finally:
        if task_broker is not None:
            await task_broker.shutdown()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(answers_router)
