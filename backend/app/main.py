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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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
    settings.frontend_dist_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
async def index():
    """Serve the built frontend when available, or explain how to run the UI."""
    index_file = settings.frontend_dist_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Frontend build not found. Run `npm run dev` inside `frontend/` for development "
                "or `npm run build` to generate `frontend/dist` for backend-served static files."
            )
        },
    )


app.mount(
    "/assets",
    StaticFiles(directory=settings.frontend_dist_dir / "assets", check_dir=False),
    name="assets",
)


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    """Serve the SPA entrypoint for frontend routes when the production build exists."""
    if full_path.startswith(("health", "query", "query_pdf", "query_image", "assets/")):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    index_file = settings.frontend_dist_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    return JSONResponse(
        status_code=404,
        content={
            "detail": (
                "Frontend route not available because `frontend/dist` does not exist yet. "
                "Use the Vite dev server or build the frontend first."
            )
        },
    )
