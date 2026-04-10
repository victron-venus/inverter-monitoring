FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir flask gunicorn

COPY server.py .
COPY deploy-local.sh .
RUN chmod +x deploy-local.sh

EXPOSE 9000

CMD ["gunicorn", "-b", "0.0.0.0:9000", "-w", "1", "server:app"]
