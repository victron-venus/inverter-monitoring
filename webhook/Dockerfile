FROM python@sha256:c3f4160f1cceaf4daa49e2b0b693cae9bb2405efe9e8f8f519dde1ea6c831248

COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /usr/local/bin/uv

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
