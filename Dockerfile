# CortexResearch engine image — shared by the API and the scheduler worker.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import torch" || true

COPY . .

# Pre-download the embedding model at build time so first run is offline-fast.
RUN python - <<'EOF' || echo "model warmup skipped (will download on first run)"
from sentence_transformers import SentenceTransformer
SentenceTransformer("all-MiniLM-L6-v2")
EOF

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
