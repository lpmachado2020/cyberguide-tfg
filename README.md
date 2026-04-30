# CyberGuide

Repositorio del Trabajo de Fin de Grado.

## Propósito

Separar por completo el desarrollo y la documentación de `CyberGuide` del proyecto previo para:

- definir una identidad y un alcance propios;
- construir un corpus público y un RAG local independientes;
- registrar decisiones, hitos y justificación técnica desde el inicio;
- reutilizar ese seguimiento como base para la memoria del TFG.

## Estructura inicial

- `docs/project-charter.md`: definición del proyecto, objetivos y alcance.
- `docs/daily-log.md`: seguimiento diario de acciones, propósito y resultados.
- `docs/decision-log.md`: decisiones de arquitectura, corpus, diseño y alcance.
- `docs/memory-outline.md`: esquema vivo de la memoria del TFG.
- `backend/`: API FastAPI, servicios de Ollama y RAG local.
- `frontend/`: interfaz del sistema.
- `scripts/`: utilidades e ingesta del corpus.
- `data/`: corpus bruto, texto procesado e índice vectorial local.

## Regla de trabajo

Todo avance relevante del proyecto debe dejar rastro en `docs/daily-log.md` y, si implica una decisión con impacto, también en `docs/decision-log.md`.

## Docker

`CyberGuide` puede levantarse en una configuración híbrida:

- `Ollama` corre en la máquina host.
- La app `FastAPI + frontend + Chroma persistence` corre en Docker.

Arranque:

```bash
docker compose up --build
```

La API quedará disponible en:

- `http://127.0.0.1:8000`

Requisitos previos en host:

1. Tener `Ollama` instalado.
2. Tener descargados los modelos requeridos:

```bash
ollama pull llama3.1:8b
ollama pull bge-m3
```

Notas:

- `docker-compose.yml` usa `host.docker.internal:11434` para que el contenedor pueda hablar con `Ollama`.
- Los datos persistentes de Chroma se guardan en volúmenes Docker para no perder el índice al recrear el contenedor.
- Si los volúmenes están vacíos, primero hay que poblar el índice ejecutando la ingesta en Docker:

```bash
docker compose run --rm cyberguide-ingest
docker compose up -d cyberguide-app
```

## Evaluación

El repositorio incluye una primera cadena de evaluación local:

1. Generar preguntas sintéticas a partir del corpus:

```bash
python scripts/generate_eval_dataset.py
```

2. Lanzarlas contra la API local:

```bash
python scripts/run_eval_benchmark.py --base-url http://127.0.0.1:8013
```

3. Juzgar automáticamente las respuestas:

```bash
python scripts/judge_eval_results.py
```

Los artefactos se guardan por defecto en:

- `data/evals/`
