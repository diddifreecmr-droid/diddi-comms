FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app_base ./app_base
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

RUN pip install --no-cache-dir -e .

EXPOSE 8040

CMD ["uvicorn", "app_base.main:app", "--host", "0.0.0.0", "--port", "8040"]

