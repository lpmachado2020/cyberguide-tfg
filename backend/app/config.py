"""Application settings for the CyberGuide backend.

Purpose:
- Centralize runtime configuration for the local RAG backend.

Inputs:
- Environment variables loaded from `backend/.env`.

Outputs:
- A cached `Settings` object shared across the application.

Used by:
- `backend/app/main.py`
- Services under `backend/app/services/`
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
REFERENCES_DIR = PROJECT_ROOT / "references"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CyberGuide Backend"
    app_version: str = "0.1.0"
    assistant_name: str = "CyberGuide"
    assistant_domain_name: str = "ciberseguridad para pymes y autonomos"
    assistant_audience: str = "pymes, autonomos y personas que necesitan orientacion practica en ciberseguridad"
    assistant_mission: str = "ofrecer conversacion util, estable y trazable a partir de un corpus local y documentos subidos"
    assistant_corpus_scope: str = "politicas, guias y materiales de INCIBE cargados localmente, mas documentos PDF o imagenes que el usuario aporte"
    assistant_scope_boundary: str = "no inventar que una fuente dice algo cuando no aparece en el corpus o en el documento activo"
    local_execution_rationale: str = "todo el sistema se ejecuta en local para preservar privacidad, mantener control total del pipeline y permitir validacion reproducible"
    local_cost_rationale: str = "el pipeline usa Ollama y Chroma en local para evitar costes por llamada a APIs externas y poder iterar gratis en desarrollo y validacion"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_model: str = "llama3.1:8b"
    ollama_embed_model: str = "bge-m3:latest"

    chroma_collection: str = "cyberguide"
    chroma_dir: Path = DATA_DIR / "vectorstore" / "chroma"
    raw_data_dir: Path = DATA_DIR / "raw"
    processed_data_dir: Path = DATA_DIR / "processed"
    runtime_audit_path: Path = processed_data_dir / "runtime_audit.ndjson"
    references_dir: Path = REFERENCES_DIR
    frontend_dir: Path = FRONTEND_DIR
    frontend_dist_dir: Path = FRONTEND_DIST_DIR

    top_k: int = 4
    max_context_chunks: int = 4
    max_context_chars_per_chunk: int = 1800


@lru_cache
def get_settings() -> Settings:
    """Return the shared application settings instance."""
    return Settings()
