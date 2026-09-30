FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/cache/huggingface HF_HUB_DISABLE_PROGRESS_BARS=1 TRANSFORMERS_VERBOSITY=error

WORKDIR /app
COPY requirements.txt requirements-local.txt ./

# CPU PyTorch by default. For a GPU image, build with
#   --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu126
# and run with --gpus all -e DEVICE=cuda.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
# Set to false for an image with only the API and Jev (a few hundred MB instead of several GB).
ARG LOCAL_MODELS=true
RUN pip install -r requirements.txt && \
    if [ "$LOCAL_MODELS" = "true" ]; then \
      pip install torch==2.14.0 --index-url "$TORCH_INDEX" && pip install -r requirements-local.txt; \
    fi

COPY app app
COPY scripts scripts
COPY web web
COPY results results
COPY LABELLING.md README.md ./

RUN useradd --create-home app && mkdir -p /cache && chown -R app /app /cache
USER app

EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
