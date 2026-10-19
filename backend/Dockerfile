# syntax=docker/dockerfile:1.7
# Two targets from one file:
#   api    - FastAPI + onnxruntime, no torch (small image, fast start)
#   worker - offline jobs (download, embed with torch CPU, ONNX export)
ARG PYTHON=python:3.12-slim-bookworm

FROM ${PYTHON} AS deps-api
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
ENV PATH=/venv/bin:$PATH
COPY requirements-api.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-api.txt

# onnxruntime only needs sympy for its offline tools; pip is not needed at runtime
FROM deps-api AS venv-api-slim
RUN pip uninstall -y sympy mpmath pip

FROM deps-api AS deps-worker
COPY requirements-worker.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 \
 && pip install -r requirements-worker.txt

FROM ${PYTHON} AS runtime-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/venv/bin:$PATH \
    DATA_DIR=/data MODEL_DIR=/models/siglip2 HF_HUB_DISABLE_TELEMETRY=1
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY app ./app
COPY migrations ./migrations
COPY config ./config

FROM runtime-base AS api
COPY --from=venv-api-slim /venv /venv
ENV ENCODER_BACKEND=onnx
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]

FROM runtime-base AS worker
COPY --from=deps-worker /venv /venv
ENV ENCODER_BACKEND=siglip
USER app
CMD ["python", "-m", "app.jobs.pipeline"]
