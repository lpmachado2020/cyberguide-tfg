# Backend

Backend inicial de `CyberGuide` basado en FastAPI, Ollama y Chroma.

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run API

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Docker run

La opción recomendada para este proyecto es híbrida:

- `Ollama` se mantiene en la máquina host
- `CyberGuide` corre en un contenedor Docker

Desde la raíz del proyecto:

```bash
docker compose up --build
```

Detalles clave:

- El contenedor expone `8000:8000`
- La app usa `OLLAMA_BASE_URL=http://host.docker.internal:11434`
- Chroma persiste en volúmenes Docker y no se pierde al recrear el contenedor

Requisitos previos:

```bash
ollama pull llama3.1:8b
ollama pull bge-m3
```

Si el volumen de Chroma aún está vacío, ejecuta primero la ingesta:

```bash
docker compose run --rm cyberguide-ingest
docker compose up -d cyberguide-app
```

## Ingest local corpus

Guarda archivos `.txt`, `.md` o `.html` en `../data/raw/` y ejecuta:

```bash
cd ..
PYTHONPATH=. python scripts/ingest_corpus.py
```

Para ingerir directamente los PDF oficiales guardados en `references/incibe-pdfs/`:

```bash
cd ..
PYTHONPATH=. python scripts/ingest_corpus.py --root references/incibe-pdfs
```

## Evaluation workflow

Desde la raíz del proyecto:

```bash
python scripts/generate_eval_dataset.py
python scripts/run_eval_benchmark.py --base-url http://127.0.0.1:8013
python scripts/judge_eval_results.py
```

Esto crea:

- un dataset sintético de preguntas sobre el corpus,
- una ejecución contra la API actual,
- y una capa de evaluación automática con scoring de corrección, grounding y seguridad.
