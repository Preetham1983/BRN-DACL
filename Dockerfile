# ──────────────────────────────────────────────
# DACL Agent — Backend (FastAPI + Uvicorn)
# ──────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Install system deps (for any C-extension packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project manifest and source
COPY pyproject.toml .
COPY src/ ./src/


# Install the package and all dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --timeout 120 --retries 5 .

# Create compiled graphs directory (persisted via Docker volume)
RUN mkdir -p compiled

# Copy any pre-compiled graphs (e.g. freight_policy_graph.json)
# so the first query doesn't require an LLM compile call
COPY compiled/ ./compiled/

# ── How imports are resolved ──────────────────────────────────────────────
# PYTHONPATH=/app/src  → if not installed
# CWD=/app  → compiled/ resolves to /app/compiled/
# ─────────────────────────────────────────────────────────────────────────

EXPOSE 8000

CMD ["uvicorn", "dacl_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
