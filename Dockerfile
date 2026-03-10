FROM python:3.11-slim AS builder

WORKDIR /build

# Install system build deps (needed for some Python C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.docker.txt .
RUN pip install --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.docker.txt


FROM python:3.11-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Runtime system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Install pre-built wheels from builder stage
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir --find-links /wheels /wheels/*.whl \
 && rm -rf /wheels

# Copy project source
COPY . .

# Collect static files (no-op without STATIC_ROOT configured, harmless)
RUN python manage.py collectstatic --noinput 2>/dev/null || true

EXPOSE 8000
