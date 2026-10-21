# Solace in one container: FastAPI serves the API and the built React app on one port.
#
#   docker build -t solace-cac .
#   docker run --rm -p 7860:7860 solace-cac                      # no keys: rules + local model
#   docker run --rm -p 7860:7860 -e ANTHROPIC_API_KEY=... -e AI_DAILY_BUDGET_USD=5 solace-cac
#
# The trained model (about 250 MB) is not in git. By default the build downloads it with
# scripts/fetch_models.sh, which checks every file against pinned sha256 hashes. If the
# files are already in backend/models in the build context and match, the download is
# skipped; any that do not match are replaced with the pinned release. Build with
# --build-arg FETCH_MODELS=0 to never download: the local files must then match the pins
# (the build stops if one does not), and with no files the app runs on the rules alone.

ARG FETCH_MODELS=1

# 1. Build the frontend. Stages 1 to 3 run on the build machine's own CPU (their output
#    does not depend on it); only the runtime stage is built for the target platform.
FROM --platform=$BUILDPLATFORM node:20-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# The /ai-disclosure and /stress-test pages render these two repo files at build time.
COPY AI-DISCLOSURE.md /app/AI-DISCLOSURE.md
COPY docs/evidence/red-flag-stress-test.md /app/docs/evidence/red-flag-stress-test.md
RUN npm run build

# 2. Get and verify the model files.
FROM --platform=$BUILDPLATFORM python:3.12-slim AS models
ARG FETCH_MODELS
ARG SOLACE_MODELS_REPO=teameuphoriainv-dot/solace-cac
ARG SOLACE_MODELS_TAG=models-v1
ARG SOLACE_MODELS_URL=
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY scripts/fetch_models.sh scripts/fetch_models.sh
COPY backend/models/ backend/models/
RUN chmod +x scripts/fetch_models.sh \
 && if [ "$FETCH_MODELS" = "1" ]; then \
      SOLACE_MODELS_REPO="$SOLACE_MODELS_REPO" SOLACE_MODELS_TAG="$SOLACE_MODELS_TAG" \
      SOLACE_MODELS_URL="$SOLACE_MODELS_URL" scripts/fetch_models.sh --force; \
    else \
      echo "FETCH_MODELS=0: skipping the download, checking local files"; \
      scripts/fetch_models.sh --verify || [ $? -eq 2 ]; \
    fi

# 3. The backend code without the model files, so the image holds them only once
#    (they come from stage 2). Nothing from this stage is kept except the copy below.
FROM --platform=$BUILDPLATFORM python:3.12-slim AS src
COPY backend/ /src/backend/
RUN rm -rf /src/backend/models/* /src/backend/tmp

# 4. Runtime image.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SOLACE_MODE=local \
    SOLACE_STATIC_DIR=/app/frontend/dist \
    SOLACE_SEED_BACKGROUND=1 \
    PORT=7860

# LightGBM needs the OpenMP runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces runs containers as uid 1000.
RUN useradd --create-home --uid 1000 solace

WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY --from=src --chown=solace:solace /src/backend/ ./
COPY --from=models --chown=solace:solace /src/backend/models/ ./models/
COPY --from=web --chown=solace:solace /app/frontend/dist /app/frontend/dist
# Uploaded photos and generated audio are written under backend/tmp. Only the folders are
# chowned here; a recursive chown would copy the 250 MB of model files into a new layer.
RUN mkdir -p /app/backend/tmp/media \
 && chown solace:solace /app/backend /app/backend/tmp /app/backend/tmp/media

USER solace
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '7860'), timeout=4)" || exit 1
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
