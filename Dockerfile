FROM python:3.12-slim AS builder
ENV POETRY_VERSION=1.8.2 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update && apt-get install --yes --no-install-recommends git build-essential autoconf automake libtool pkg-config libffi-dev && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root --no-ansi
RUN .venv/bin/python -c "from acorn.acorn import Acorn; assert callable(getattr(Acorn, 'default_handle', None)), 'Update safebox-acorn and poetry.lock: default_handle is required'"

RUN .venv/bin/python -c "from acorn.acorn import Acorn; assert callable(getattr(Acorn, 'quote_ecash_transfer', None)), 'Update safebox-acorn and poetry.lock: sender-paid fee quotes are required'"

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --uid 10001 --create-home oakgate && install -d -o oakgate -g oakgate -m 700 /app/data
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY pos ./pos
COPY assets/branding/oakgate-logo-flat.png ./assets/branding/oakgate-logo-flat.png
USER oakgate
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log", "--loop", "asyncio"]
