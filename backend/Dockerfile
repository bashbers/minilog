FROM docker.io/library/python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels .

FROM docker.io/library/python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN addgroup --system minilog \
    && adduser --system --ingroup minilog minilog \
    && mkdir -p /data \
    && chown minilog:minilog /data
WORKDIR /app

COPY --from=build /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels minilog-api \
    && rm -rf /wheels
COPY alembic.ini ./
COPY alembic ./alembic

USER minilog
EXPOSE 8000
CMD ["minilog-start"]
