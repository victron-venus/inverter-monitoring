FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask gunicorn

COPY server.py .
COPY deploy-local.sh .
RUN chmod +x deploy-local.sh

EXPOSE 9000

CMD ["gunicorn", "-b", "0.0.0.0:9000", "-w", "1", "server:app"]
