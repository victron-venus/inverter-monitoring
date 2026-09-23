FROM python@sha256:be8ccd085666c34273c9dc5607c9842f8b2e3116128aae45148ce164c07ce09d

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-build
ENV PATH="/app/.venv/bin:$PATH"

COPY webhook/server.py .
COPY webhook/deploy-local.sh .
RUN chmod +x deploy-local.sh \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin webhook
USER webhook

EXPOSE 9000

CMD ["gunicorn", "-b", "127.0.0.1:9000", "-w", "1", "server:app"]
