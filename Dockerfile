FROM python:3.13.9-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.27 /uv /bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./

RUN uv sync --frozen --no-install-project

COPY . .
