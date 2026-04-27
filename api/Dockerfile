# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS builder

WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --upgrade pip build && python -m build --wheel

FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install /tmp/*.whl && rm /tmp/*.whl

# Bootstrap scripts + alembic config so the container can self-migrate and
# self-seed on first deploy (see scripts/bootstrap_prod.py for the contract).
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/
COPY scripts/ /app/scripts/

RUN useradd --create-home --shell /bin/bash app
USER app

EXPOSE 8000
# ENTRYPOINT runs migrations + conditional seed every container start, then
# execs the requested CMD. Both api and worker services share this image —
# only the CMD differs (uvicorn vs `parcelpulse-scheduler`).
ENTRYPOINT ["/bin/sh", "-c", "python /app/scripts/bootstrap_prod.py && exec \"$@\"", "--"]
CMD ["uvicorn", "parcelpulse.main:app", "--host", "0.0.0.0", "--port", "8000"]
