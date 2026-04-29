FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Chromium is already installed in the base image — just register it
RUN playwright install chromium

COPY alembic.ini ./alembic.ini
COPY backend/ ./backend/

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
