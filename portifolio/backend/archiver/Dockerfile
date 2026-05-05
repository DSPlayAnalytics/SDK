FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG ANALYTICS_GID=10001
ARG APP_UID=10001

RUN groupadd --system --gid ${ANALYTICS_GID} analytics \
    && useradd  --system --uid ${APP_UID} --gid analytics --create-home \
                --shell /usr/sbin/nologin --comment "portifolio archiver" app

WORKDIR /app

# Reusa requirements.txt do backend (archiver compartilha boto3, APScheduler,
# influxdb-client, psycopg). Build context e backend/ — Dockerfile referenciado
# como `dockerfile: archiver/Dockerfile` no compose.
COPY --chown=app:analytics requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=app:analytics . .

USER app:analytics

# Sidecar long-running — APScheduler roda em foreground, container fica vivo.
CMD ["python", "-m", "archiver.main"]
