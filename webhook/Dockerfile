FROM python:3.14-slim@sha256:f54c5f39326ef06c7cb7f5fc57025aa5b7a1d3367cea42d8b5d3c8e082338ec5

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
