FROM python:3.14-slim@sha256:3fa9f1158b0d8b5029c357770bd522e7955546ffc5db885d8b366ec4a687afd4

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
