# Панель «Почтамт» и воркер в одном образе.
# Данные (config.txt, .env, сессии, база) живут на хосте в ./data — образ их не содержит.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# рабочая папка — том с данными: там config.txt, .env, *.session, panel.db
WORKDIR /data
ENV PYTHONPATH=/app \
    SENDERX_CONFIG=/data/config.txt \
    SENDERX_DB=/data/panel.db \
    PANEL_PORT=8765

EXPOSE 8765
CMD ["python", "-m", "panel.app"]
