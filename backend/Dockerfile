FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN addgroup --system minilog \
    && adduser --system --ingroup minilog minilog \
    && mkdir -p /data \
    && chown minilog:minilog /data
WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
RUN python -m pip install .

USER minilog
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn minilog.main:app --host 0.0.0.0 --port 8000 --workers 1"]
