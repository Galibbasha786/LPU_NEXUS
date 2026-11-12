FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN tesseract --version && tesseract --list-langs | grep -qx eng

COPY . .
RUN python scripts/train_placement_model.py
RUN DEBUG=True SECRET_KEY=static-build-placeholder-not-a-secret python manage.py collectstatic --noinput

CMD ["sh", "-c", "python manage.py check --deploy --fail-level ERROR && python manage.py migrate --noinput && exec daphne -b 0.0.0.0 -p ${PORT:-10000} lpu_nexus.asgi:application"]
