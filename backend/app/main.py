"""FastAPI entrypoint for the CyberGuide backend.

Purpose:
- Expose the first API routes for health checks and local RAG queries.

Inputs:
- HTTP requests from the frontend or local tests.

Outputs:
- JSON API responses.

Used by:
- Local development through Uvicorn.
- Future frontend integration.
"""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .schemas import HealthResponse, QueryRequest, QueryResponse
from .services.ingestion import prepare_chunks_from_text, read_pdf_bytes
from .services.ollama_client import OllamaClient
from .services.ocr_service import OCRService
from .services.rag import RagService
from .services.session_store import SessionStore
from .services.vector_store import VectorStore


settings = get_settings()
vector_store = VectorStore(settings)
ollama_client = OllamaClient(settings)
ocr_service = OCRService()
session_store = SessionStore()
rag_service = RagService(settings, ollama_client, vector_store, session_store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Ensure required local directories exist before serving requests."""
    settings.raw_data_dir.mkdir(parents=True, exist_ok=True)
    settings.processed_data_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.frontend_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return a basic service health snapshot."""
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        version=settings.app_version,
        chat_model=settings.ollama_chat_model,
        embed_model=settings.ollama_embed_model,
    )


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """Run the local RAG flow for a user query."""
    return await rag_service.answer(request)


@app.post("/query_pdf", response_model=QueryResponse)
async def query_pdf(
    message: str = Form(...),
    session_id: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
) -> QueryResponse:
    """Run a temporary RAG flow using an uploaded PDF or the active PDF session."""
    if file and file.content_type not in {"application/pdf", "application/octet-stream"}:
        return QueryResponse(
            answer="Por ahora solo puedo procesar archivos PDF en esta ruta de consulta.",
            sources=[],
            model=settings.ollama_chat_model,
            mode="pdf",
            session_id=session_id or "",
            document_title=None,
        )

    prepared_chunks = None
    title = None
    if file:
        file_bytes = await file.read()
        extracted_text = read_pdf_bytes(file_bytes)
        title = file.filename or "uploaded pdf"
        prepared_chunks = prepare_chunks_from_text(
            text=extracted_text,
            document_key=f"uploaded:{title}",
            title=title.rsplit(".", 1)[0],
            source_url="",
        )
        for chunk in prepared_chunks:
            chunk.metadata["source_kind"] = "pdf"
    return await rag_service.answer_with_pdf(
        session_id=session_id,
        question=message,
        prepared_chunks=prepared_chunks,
        title=title,
    )


@app.post("/query_image", response_model=QueryResponse)
async def query_image(
    message: str = Form(...),
    session_id: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
) -> QueryResponse:
    """Run OCR over an uploaded image and answer using the extracted text."""
    allowed_types = {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "application/octet-stream",
    }
    if file and file.content_type not in allowed_types:
        return QueryResponse(
            answer="Por ahora solo puedo procesar imagenes PNG, JPG o WEBP en esta ruta de consulta.",
            sources=[],
            model=settings.ollama_chat_model,
            mode="image",
            session_id=session_id or "",
            document_title=None,
            trace=None,
        )

    prepared_chunks = None
    title = None
    ocr_segments = 0
    if file:
        image_bytes = await file.read()
        extraction = ocr_service.extract_text(image_bytes)
        title = file.filename or "uploaded image"
        ocr_segments = extraction.segment_count
        prepared_chunks = prepare_chunks_from_text(
            text=extraction.text,
            document_key=f"uploaded:{title}",
            title=title.rsplit(".", 1)[0],
            source_url="",
        )
        for chunk in prepared_chunks:
            chunk.metadata["source_kind"] = "ocr-image"

    return await rag_service.answer_with_image(
        session_id=session_id,
        question=message,
        prepared_chunks=prepared_chunks,
        title=title,
        ocr_segments=ocr_segments,
    )


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the local CyberGuide interface."""
    return FileResponse(settings.frontend_dir / "index.html")


app.mount(
    "/assets",
    StaticFiles(directory=settings.frontend_dir / "assets"),
    name="assets",
)
