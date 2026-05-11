FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Group GID 10001 deve bater com o grupo `analytics` do host (criado pela
# role base do Ansible). Bind-mounts ficam compartilhados via grupo.
ARG ANALYTICS_GID=10001
ARG APP_UID=10001

RUN groupadd --system --gid ${ANALYTICS_GID} analytics \
    && useradd  --system --uid ${APP_UID} --gid analytics --create-home \
                --shell /usr/sbin/nologin --comment "portifolio backend" app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential=12.9 \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=app:analytics requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=app:analytics . .

# security.log e demais writes vao para `/app/`. Garantir que o user app pode
# escrever; em producao, prefira volume nomeado ou stdout via syslog driver.
RUN install -d -o app -g analytics -m 2770 /app

USER app:analytics

EXPOSE 5000

# Em producao, gunicorn com worker eventlet (monkey_patch automatico) serve
# Flask + Socket.IO. `-w 1` e intencional: SocketIO exige sticky sessions ou
# message queue (Redis) para multi-worker; 1 worker eventlet com greenlets
# leves da concorrencia suficiente para o trafego atual. Para dev local,
# rodar `python app.py` continua funcionando via socketio.run().
CMD ["gunicorn", \
     "--worker-class", "eventlet", \
     "-w", "1", \
     "-b", "0.0.0.0:5000", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
