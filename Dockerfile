FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/huggingface HF_HUB_DISABLE_PROGRESS_BARS=1 TRANSFORMERS_VERBOSITY=error \
    APP_ENV=production BACKENDS=catalogue,jev COMPLIANCE_DB_PATH=/data/compliance.kuzu \
    EVAL_ENABLED=false ENABLE_DEMO_ENDPOINTS=false ENABLE_DOCS=false

WORKDIR /app
COPY requirements.txt requirements-local.txt ./

# CPU PyTorch by default. For a GPU image, build with
#   --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu126
# and run with --gpus all -e DEVICE=cuda.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
# Production defaults to the API plus hosted Jev. Opt in to local model weights.
ARG LOCAL_MODELS=false
RUN pip install -r requirements.txt && \
    if [ "$LOCAL_MODELS" = "true" ]; then \
      pip install torch==2.14.0 --index-url "$TORCH_INDEX" && pip install -r requirements-local.txt; \
    fi

COPY app app
COPY scripts scripts
COPY web web
COPY results results
COPY LABELLING.md README.md PRODUCTION.md SECURITY.md ./

RUN useradd --create-home app && mkdir -p /cache /data && chown -R app /app /cache /data
USER app

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
