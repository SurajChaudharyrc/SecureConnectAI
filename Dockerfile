# SecureConnect-AI — production image (chat-focused, slim; no TensorFlow).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=prod \
    DEEPFACE_ENABLED=false \
    PORT=8000

WORKDIR /app

# Install deps first for layer caching.
COPY backend/requirements-prod.txt /app/backend/requirements-prod.txt
RUN pip install --no-cache-dir -r /app/backend/requirements-prod.txt

# App code + bundled vanilla frontend (incl. self-hosted fonts under assets/).
COPY backend /app/backend
COPY frontend /app/frontend
COPY docker-start.sh /app/docker-start.sh
RUN chmod +x /app/docker-start.sh

EXPOSE 8000
CMD ["/app/docker-start.sh"]
