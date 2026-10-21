# Deploy webserver billing ke Hugging Face Spaces (SDK Docker, port 7860).
# Berkas ini berada di root Space; isi paket server/ disalin dari repo utama.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ server/

ENV PYTHONUNBUFFERED=1 \
    PORT=7860 \
    APP_ENV=production \
    DATABASE_URL=sqlite:////data/billing.db

EXPOSE 7860
ENTRYPOINT ["bash", "entrypoint.sh"]
