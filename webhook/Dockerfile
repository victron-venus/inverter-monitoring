FROM python@sha256:4fad23465a06cc5149a541fbec6f87e234a64dc0550f6bfdd2d290d8f03240df

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
