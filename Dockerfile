FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/ledger
COPY requirements.lock .
RUN pip install -r requirements.lock
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY alembic ./alembic
RUN useradd --uid 10001 --create-home ledger
USER ledger
EXPOSE 8000

FROM base AS test
USER root
COPY requirements-test.lock .
RUN pip install -r requirements-test.lock
COPY tests ./tests
COPY lab ./lab
COPY scripts ./scripts
USER ledger
ENV PYTEST_ADDOPTS="-p no:cacheprovider" HYPOTHESIS_STORAGE_DIRECTORY=/tmp/hypothesis

FROM base AS runtime
