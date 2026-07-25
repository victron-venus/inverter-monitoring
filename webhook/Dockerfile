FROM python@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --only-binary :all: flask==3.1.3 gunicorn==26.0.0

COPY server.py .
COPY deploy-local.sh .
RUN chmod +x deploy-local.sh

EXPOSE 9000

CMD ["gunicorn", "-b", "127.0.0.1:9000", "-w", "1", "server:app"]
