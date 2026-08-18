from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .api import reader
from .services.workers import start_workers
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from talkingdb.models.failure.failure import DocumentFailure
import threading


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=start_workers, daemon=True).start()
    yield
    # Shutdown code can go here


app = FastAPI(lifespan=lifespan, title="Package Content Elementizer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DocumentFailure)
async def _document_failure_handler(
    request: Request, exc: DocumentFailure
) -> JSONResponse:
    """Carry a declared failure reason across the service boundary."""
    return JSONResponse(
        status_code=422,
        content={
            "failure_reason": exc.reason.value,
            "detail": exc.detail,
        },
    )


app.include_router(reader.router)
