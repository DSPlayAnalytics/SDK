from flask import Blueprint, Flask, jsonify, make_response, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit, disconnect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import hmac
import os
import secrets
import hashlib
import time
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps
import logging
import sys

from config import config
from influxdb_service import get_influxdb_service

# ==================== CONFIGURAÇÃO DE SEGURANÇA ====================

# ✅ CONFIGURAR APPLICATION CONTEXT PARA /api/
app = Flask(__name__)
env = os.environ.get("FLASK_ENV", "development")
app.config.from_object(config[env])

# Blueprint canonico — paths SEM prefixo `/api/` em todos os ambientes.
# Externamente, `api.dsplayground.com.br` proxia direto e `dsplayground.com.br/api/*`
# strippa o prefixo no nginx antes de chegar aqui (ver ark/nginx/portifolio.conf).
api_bp = Blueprint('api', __name__)

# ✅ CONFIGURAÇÕES DE SEGURANÇA AVANÇADAS
SECRET_KEY = app.config.get('SECRET_KEY') or secrets.token_urlsafe(32)
app.secret_key = SECRET_KEY

# Configurações de sessão seguras
app.config.update(
    SESSION_COOKIE_SECURE=env == 'production',
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    SESSION_COOKIE_NAME='portfolio_session',
    WTF_CSRF_TIME_LIMIT=None,
    # ✅ CONFIGURAÇÃO PARA PROXY REVERSO
    APPLICATION_ROOT='/api' if env == 'production' else '/',
    PREFERRED_URL_SCHEME='https' if env == 'production' else 'http'
)

# ✅ RATE LIMITING
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# ✅ LOGGING SEGURO com rotacao
from logging.handlers import RotatingFileHandler


class SafeRotatingFileHandler(RotatingFileHandler):
    def __init__(self, filename, max_bytes=10 * 1024 * 1024, backup_count=5, encoding='utf-8'):
        super().__init__(filename, maxBytes=max_bytes, backupCount=backup_count, encoding=encoding)


class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            msg = msg.encode('ascii', errors='ignore').decode('ascii')
            stream = self.stream
            stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[SafeStreamHandler(sys.stdout)],
    force=True
)

# security.log recebe SO eventos do security_logger — CrowdSec parsa esse arquivo
# e qualquer ruido de logger root (Flask/Werkzeug/libs) geraria linhas unparsed.
security_logger = logging.getLogger('security')
security_logger.setLevel(logging.INFO)
_security_handler = SafeRotatingFileHandler('security.log')
_security_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
security_logger.addHandler(_security_handler)
security_logger.propagate = False

# ✅ CORS configurado por ambiente
cors_origins = app.config.get("CORS_ORIGINS", ["http://localhost:5173"])
_cors_origins_set = frozenset(o.rstrip("/") for o in cors_origins if o)

# Lista estatica cobre subdominios proprios (api.X, app.X, portifolio.X) +
# landing CF Pages. Origins de SDKs em sites de clientes vem do Postgres
# em runtime via `_origins_dinamicos` (instanciado abaixo, apos tenants_repo).
CORS(app,
     origins=cors_origins,
     supports_credentials=True,
     allow_headers=['Content-Type', 'Authorization', 'X-Session-Token',
                    'X-Forwarded-For', 'X-Forwarded-Proto',
                    'X-SDK-Schema-Version'],
     methods=['GET', 'POST', 'PATCH', 'OPTIONS']
)

# Singleton populado apos `_tenants_repo_singleton` ser criado. Hooks abaixo
# (cors_dinamico_preflight + cors_dinamico_resposta) checam se ele existe
# antes de usar — defensivo pra caso o boot falhe.
_origins_dinamicos = None  # type: ignore[assignment]


def _origin_socketio_permitido(origin):
    """Callable pra `cors_allowed_origins` do python-socketio.

    Resolvido em runtime: estatico passa direto; dinamico consulta
    OriginsDinamicos quando disponivel.
    """
    if not origin:
        return False
    normalizado = origin.rstrip("/")
    if normalizado in _cors_origins_set:
        return True
    if _origins_dinamicos is None:
        return False  # antes do boot completo, so estatico
    return _origins_dinamicos.permitido(normalizado)


# ✅ SOCKETIO COM SUPORTE A PROXY REVERSO
# cors_allowed_origins aceita callable em python-socketio — usa o mesmo
# validador dinamico do HTTP.
socketio_config = {
    'cors_allowed_origins': _origin_socketio_permitido,
    'logger': False,
    'engineio_logger': False,
    'ping_timeout': 60,
    'ping_interval': 25
}

# Path canonico SEM /api/. Externalmente o cliente acessa
# `https://api.dsplayground.com.br/socket.io/` (proxy direto) ou
# `https://dsplayground.com.br/api/socket.io/` (nginx strippa /api/).
# Backend sempre escuta em /socket.io/.
socketio_config['path'] = '/socket.io'

# async_mode 'eventlet' habilita upgrade WebSocket. O Dockerfile de
# producao roda 'gunicorn --worker-class eventlet', entao o Socket.IO
# precisa do mesmo loop async em todos os ambientes — sem isso o
# handshake retorna `upgrades:[]` e o cliente cicla em polling.
# Em ambientes de teste local sem eventlet (Windows), passe
# SOCKETIO_ASYNC_MODE=threading no env pra evitar import error.
socketio_config['async_mode'] = os.environ.get('SOCKETIO_ASYNC_MODE', 'eventlet')

socketio = SocketIO(app, **socketio_config)

# ==================== MIDDLEWARE PARA PROXY REVERSO ====================

@app.before_request
def before_request():
    """Middleware para lidar com headers de proxy reverso"""
    # Configurar HTTPS quando atrás de proxy
    if request.headers.get('X-Forwarded-Proto') == 'https':
        request.environ['wsgi.url_scheme'] = 'https'
    
    # Configurar IP real do cliente
    if request.headers.get('X-Forwarded-For'):
        request.environ['REMOTE_ADDR'] = request.headers.get('X-Forwarded-For').split(',')[0].strip()

def log_safe(logger, level, message, *args):
    """Log seguro que remove emojis problemáticos"""
    emoji_map = {
        '🔧': '[CONFIG]', '🔒': '[SECURITY]', '✅': '[SUCCESS]',
        '⚠️': '[WARNING]', '❌': '[ERROR]', '🔌': '[WEBSOCKET]',
        '📊': '[ANALYTICS]', '🚫': '[BLOCKED]', '🧹': '[CLEANUP]',
        '⏰': '[TIMEOUT]', '🌐': '[REMOTE]', '💻': '[LOCAL]', '🔍': '[DEBUG]'
    }

    safe_message = message
    for emoji, replacement in emoji_map.items():
        safe_message = safe_message.replace(emoji, replacement)

    getattr(logger, level)(safe_message, *args)


# ==================== LOG SCRUBBING (anti-leak) ====================
# Filter aplicado em handlers de log pra redijir credenciais que possam ter
# vazado em mensagens (exception traces, error logs, .env paths, etc). Cobre
# os padroes mais comuns. NAO substitui sanitizacao no call site — e rede de
# seguranca pra eventos imprevistos (ex: Flask exception logger).
import re as _re_logscrub

_LOG_PATTERNS = [
    # postgres://user:senha@host
    (_re_logscrub.compile(r'(postgres(?:ql)?://[^:\s"\']+:)([^@\s"\']+)(@)'),
     r'\1***\3'),
    # Bearer <token>
    (_re_logscrub.compile(r'(Bearer\s+)[A-Za-z0-9._\-]+'), r'\1***'),
    # Authorization: Bearer ...
    (_re_logscrub.compile(r'(Authorization["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+'),
     r'\1***'),
    # X-API-Key, x-admin-token etc
    (_re_logscrub.compile(r'(X-(?:API|Admin|Auth)-(?:Key|Token)["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+',
                          _re_logscrub.IGNORECASE),
     r'\1***'),
    # ?token=<jwt>
    (_re_logscrub.compile(r'([?&]token=)[A-Za-z0-9._\-]+'), r'\1***'),
    # SECRET_KEY=... e parentes
    (_re_logscrub.compile(r'([A-Z_]*(?:SECRET|TOKEN|PASSWORD|KEY|API_KEY)[A-Z_]*\s*[:=]\s*)([^\s"\',}]+)'),
     r'\1***'),
    # Cookie: cliente_session=...
    (_re_logscrub.compile(r'(cliente_session=)[^;\s]+'), r'\1***'),
    # JWT crus (header.payload.signature)
    (_re_logscrub.compile(r'\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b'),
     'eyJ***.***.***')
]


class _LogScrubFilter(logging.Filter):
    """Redije credenciais comuns no record antes de gravar no handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        scrubbed = msg
        for pattern, replacement in _LOG_PATTERNS:
            scrubbed = pattern.sub(replacement, scrubbed)
        if scrubbed != msg:
            # Ja interpolou args; sobrescreve msg e zera args pra evitar
            # double-format que crashe em LogRecord.getMessage.
            record.msg = scrubbed
            record.args = ()
        return True


# Aplica filter em todos os handlers conhecidos.
_scrub = _LogScrubFilter()
for _h in logging.getLogger().handlers:
    _h.addFilter(_scrub)
_security_handler.addFilter(_scrub)

# ==================== SISTEMA DE SESSÕES (mantido igual) ====================
active_sessions = {}
session_metrics = defaultdict(lambda: {
    'requests_count': 0, 'last_activity': time.time(),
    'ip_address': None, 'user_agent': None,
    'security_score': 100, 'warnings': []
})
suspicious_ips: dict[str, float] = {}   # ip -> ban_expira_em (timestamp)
rate_limit_violations = defaultdict(list)
# Threshold do anti-abuse. SDK de analytics em batch envia ~12 frames/min/sessao
# (1 batch a cada 5s + page_view + scroll + cliques + ping/pong). Em prod cada
# IP e um end-user; em dev local TODO trafego vem do mesmo IP da bridge Docker.
SUSPICIOUS_REQS_PER_MIN = int(os.environ.get('ANTIABUSE_REQS_PER_MIN', '600'))
SUSPICIOUS_BAN_TTL = int(os.environ.get('ANTIABUSE_BAN_TTL_SECONDS', '300'))
# IPs internos (loopback, docker bridges, redes privadas) nao sao banidos —
# evita auto-DoS do dev local. Em prod o trafego chega via X-Forwarded-For
# do nginx, que e IP publico real.
ANTIABUSE_SKIP_PRIVATE = os.environ.get('ANTIABUSE_SKIP_PRIVATE', 'true').lower() == 'true'

def generate_session_token():
    return secrets.token_urlsafe(32)

def create_session_fingerprint(request):
    user_agent = request.headers.get('User-Agent', '')
    ip_address = request.environ.get('REMOTE_ADDR', '')
    accept_language = request.headers.get('Accept-Language', '')
    fingerprint_string = f"{ip_address}:{user_agent}:{accept_language}"
    return hashlib.sha256(fingerprint_string.encode()).hexdigest()[:16]

def validate_session_integrity(session_id: str, request) -> bool:
    if session_id not in active_sessions:
        return False
    session_data = active_sessions[session_id]
    current_fingerprint = create_session_fingerprint(request)
    if session_data.get('fingerprint') != current_fingerprint:
        log_safe(security_logger, 'warning', f"[SECURITY] Possivel session hijacking detectado: {session_id}")
        return False
    if time.time() - session_data.get('created_at', 0) > 3600:
        log_safe(security_logger, 'info', f"[TIMEOUT] Sessao expirada: {session_id}")
        return False
    return True

def _ip_eh_privado(ip: str) -> bool:
    """Loopback, docker bridges e redes privadas — nao sao banidos."""
    if not ip or ip == 'unknown':
        return True
    try:
        from ipaddress import ip_address as parse_ip
        addr = parse_ip(ip)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except (ValueError, ImportError):
        return False


def check_suspicious_activity(session_id: str, request) -> bool:
    ip_address = request.environ.get('REMOTE_ADDR', '')
    current_time = time.time()

    # Pula bloqueio para IPs internos (dev local, traffic via docker bridge).
    if ANTIABUSE_SKIP_PRIVATE and _ip_eh_privado(ip_address):
        return True

    # Ban com TTL: se expirou, remove e segue normal.
    ban_expira = suspicious_ips.get(ip_address)
    if ban_expira is not None:
        if ban_expira > current_time:
            log_safe(security_logger, 'warning', f"[BLOCKED] IP suspeito tentando acesso: {ip_address}")
            return False
        del suspicious_ips[ip_address]

    # Janela movel de 60s.
    rate_limit_violations[ip_address] = [
        t for t in rate_limit_violations[ip_address] if current_time - t < 60
    ]
    if len(rate_limit_violations[ip_address]) > SUSPICIOUS_REQS_PER_MIN:
        log_safe(security_logger, 'warning',
                 f"[WARNING] Rate limit excedido para IP: {ip_address} "
                 f"({len(rate_limit_violations[ip_address])} req/min, ban {SUSPICIOUS_BAN_TTL}s)")
        suspicious_ips[ip_address] = current_time + SUSPICIOUS_BAN_TTL
        return False
    rate_limit_violations[ip_address].append(current_time)
    return True

def security_middleware(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_id = request.sid if hasattr(request, 'sid') else 'http'
        if not check_suspicious_activity(session_id, request):
            log_safe(security_logger, 'warning',
                     f"evento=acesso_bloqueado session_id={session_id} "
                     f"ip={request.environ.get('REMOTE_ADDR', 'unknown')} motivo=suspicious")
            return jsonify({"error": "Acesso negado"}), 403
        session_id = request.sid if hasattr(request, 'sid') else request.headers.get('X-Session-Token')
        if session_id:
            session_metrics[session_id]['requests_count'] += 1
            session_metrics[session_id]['last_activity'] = time.time()
            session_metrics[session_id]['ip_address'] = request.environ.get('REMOTE_ADDR', '')
        return f(*args, **kwargs)
    return decorated_function

# ==================== CACHE TEMPORAL ====================
temporal_stats_cache = {
    "total_sessions": 0, "active_sessions": {},
    "realtime_data": defaultdict(list), "last_cleanup": time.time(), "security_events": []
}

TEMPORAL_CONFIG = {
    "REALTIME_INTERVAL": app.config.get("TEMPORAL_REALTIME_INTERVAL", 5000),
    "REGULAR_INTERVAL": app.config.get("TEMPORAL_REGULAR_INTERVAL", 15000),
    "CACHE_CLEANUP_INTERVAL": app.config.get("TEMPORAL_CLEANUP_INTERVAL", 300),
    "MAX_CACHE_ENTRIES": app.config.get("TEMPORAL_CACHE_SIZE", 1000)
}

def cleanup_temporal_cache():
    current_time = time.time()
    if current_time - temporal_stats_cache["last_cleanup"] > TEMPORAL_CONFIG["CACHE_CLEANUP_INTERVAL"]:
        expired_sessions = [
            sid for sid, data in active_sessions.items()
            if current_time - data.get('last_activity', 0) > 3600
        ]
        for sid in expired_sessions:
            del active_sessions[sid]
            if sid in temporal_stats_cache["active_sessions"]:
                del temporal_stats_cache["active_sessions"][sid]
        if expired_sessions:
            log_safe(security_logger, 'info', f"[CLEANUP] Removidas {len(expired_sessions)} sessoes expiradas")
        for page in temporal_stats_cache["realtime_data"]:
            if len(temporal_stats_cache["realtime_data"][page]) > TEMPORAL_CONFIG["MAX_CACHE_ENTRIES"]:
                temporal_stats_cache["realtime_data"][page] = temporal_stats_cache["realtime_data"][page][-TEMPORAL_CONFIG["MAX_CACHE_ENTRIES"]//2:]
        temporal_stats_cache["last_cleanup"] = current_time

# Inicializar InfluxDB
try:
    influxdb_service = get_influxdb_service()
    log_safe(security_logger, 'info', "[SUCCESS] InfluxDB service inicializado com sucesso")
except Exception as e:
    log_safe(security_logger, 'warning', f"[WARNING] Erro ao inicializar InfluxDB: {str(e)}")
    influxdb_service = None

# Servico de ingestao — handler Socket.IO apenas delega para este servico.
from ingestao import ServicoIngestao  # noqa: E402
from ingestao.cardinalidade import obter_tracker as obter_cardinalidade_tracker  # noqa: E402
from auth.sites_cache import SitesCache  # noqa: E402
# sites_cache + tenants_repo + cardinalidade sao injetados apos o tenants_repo
# singleton estar pronto (ver bloco "Auth multi-tenant" abaixo).
servico_ingestao = ServicoIngestao(influxdb_service=influxdb_service)

# ==================== AUTENTICACAO MULTI-TENANT ====================
from auth.jwt_service import obter_servico as obter_jwt_service  # noqa: E402
from auth.middleware import AuthError, normalizar_origin, validar_token_socketio  # noqa: E402
from auth.routes import auth_bp  # noqa: E402
from auth.tenants_repo import obter_repo as obter_tenants_repo  # noqa: E402

try:
    _tenants_repo_singleton = obter_tenants_repo(app.config["TENANTS_DATABASE_URL"])
    obter_jwt_service(
        keys_dir=app.config["JWT_KEYS_DIR"],
        audience=app.config["JWT_AUDIENCE"],
    )
    # Wire bucket-routing + quota + cardinalidade no servico de ingestao.
    servico_ingestao.sites_cache = SitesCache(_tenants_repo_singleton)
    servico_ingestao.tenants_repo = _tenants_repo_singleton
    servico_ingestao.cardinalidade_tracker = obter_cardinalidade_tracker()

    # CORS dinamico: ativa lookup em site_dominios pra Origins fora da lista
    # estatica. Necessario pra SDKs em sites de clientes recem-cadastrados
    # funcionarem sem exigir edit de vault + ansible-apply.
    from auth.origins_dinamicos import OriginsDinamicos  # noqa: E402
    _origins_dinamicos = OriginsDinamicos(
        origins_estaticos=cors_origins,
        tenants_repo=_tenants_repo_singleton,
        ttl_segundos=int(os.environ.get("CORS_DINAMICO_TTL_SEGUNDOS", "60")),
    )

    # Housekeeping de embed_jwt_revogados — best-effort. TTL_MAX do JWT
    # embed e 24h hoje; mantemos 48h de retencao pra cobrir clock-skew
    # e re-rotacoes proximas. Nao quebra boot se falhar.
    try:
        _apagados = _tenants_repo_singleton.purgar_embed_jwt_revogados_antigos(retencao_horas=48)
        if _apagados:
            log_safe(security_logger, 'info',
                     f"[BOOT] embed_jwt_revogados housekeeping: apagados={_apagados}")
    except Exception as _e:
        log_safe(security_logger, 'warning',
                 f"[BOOT] housekeeping embed_jwt_revogados falhou: {type(_e).__name__}")

    log_safe(security_logger, 'info', "[SUCCESS] Auth multi-tenant inicializado")
except Exception as e:
    log_safe(security_logger, 'error', f"[ERROR] Falha ao inicializar auth: {str(e)}")
    raise


# ==================== CORS dinamico (hooks Flask) ====================
# Hooks rodam por requisicao. flask-cors ja cobre static origins (subdominios
# proprios + landing CF). Quando origin nao bate static, consultamos
# OriginsDinamicos pra ver se eh cliente registrado em site_dominios.

@app.before_request
def cors_dinamico_preflight():
    """Responde OPTIONS preflight pra origins dinamicos.

    flask-cors so responde preflight pra origins na lista estatica. Pra cliente
    registrado mas fora da lista, manualmente devolve 204 com headers CORS.
    """
    if request.method != 'OPTIONS':
        return None
    origin = request.headers.get('Origin')
    if not origin:
        return None
    normalizado = origin.rstrip('/')
    if normalizado in _cors_origins_set:
        return None  # flask-cors handles
    if _origins_dinamicos is None or not _origins_dinamicos.permitido(normalizado):
        return None  # nao permitido — flask-cors decidira (sem headers)

    # Permitido dinamico: monta resposta de preflight manualmente
    resp = make_response('', 204)
    resp.headers['Access-Control-Allow-Origin'] = origin
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = (
        'Content-Type, Authorization, X-Session-Token, '
        'X-Forwarded-For, X-Forwarded-Proto, X-SDK-Schema-Version'
    )
    resp.headers['Access-Control-Max-Age'] = '86400'
    resp.headers['Vary'] = 'Origin'
    return resp


@app.after_request
def cors_dinamico_resposta(resp):
    """Adiciona headers CORS pra response de origin dinamico, quando flask-cors
    nao cobriu (origin fora da lista estatica)."""
    if resp.headers.get('Access-Control-Allow-Origin'):
        return resp  # flask-cors ja setou (origin estatico)
    origin = request.headers.get('Origin')
    if not origin:
        return resp
    normalizado = origin.rstrip('/')
    if normalizado in _cors_origins_set:
        return resp  # estatico — flask-cors devia ter setado, nao mexe
    if _origins_dinamicos is None or not _origins_dinamicos.permitido(normalizado):
        return resp  # nao permitido — sem headers, browser bloqueia
    resp.headers['Access-Control-Allow-Origin'] = origin
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    vary_atual = resp.headers.get('Vary', '')
    resp.headers['Vary'] = ('Origin, ' + vary_atual) if vary_atual else 'Origin'
    return resp


app.register_blueprint(auth_bp, url_prefix='/auth')


# ==================== METRICS PROMETHEUS ====================
# Endpoint /metrics consumido pelo Prometheus (job 'portifolio-backend' em
# ark/monitoring/prometheus/prometheus.yml). Sem auth — Prometheus scrape de
# dentro da rede docker (backend:5000); externamente nginx nao expoe /metrics.
from metrics import obter_metrics, registrar_endpoint as _registrar_metrics_endpoint  # noqa: E402

_metrics_service = obter_metrics()
_registrar_metrics_endpoint(app, _metrics_service)
# /metrics nao precisa rate-limit — Prometheus scrape em intervalo fixo
limiter.exempt(app.view_functions['prometheus_metrics'])
log_safe(security_logger, 'info', "[SUCCESS] Metrics Prometheus em /metrics")


# /auth/sdk-token chamado por todo browser que carrega landing publica —
# default flask-limiter (50/h) bate em segundos com handful de page loads.
# Defesa real e em camadas: nginx zone=cliente_auth (10r/s burst 10, applied no
# location /auth/sdk-token) + quotas.emissoes_jwt_por_minuto (Postgres,
# per-publishable_key). Aqui no Flask aplicamos um limite per-IP generoso
# (60/min) — ja absorve burst de page reload e barra brute force absurdo
# (era unlimited por exempt).
from auth.routes import emitir_sdk_token  # noqa: E402
limiter.limit("60 per minute")(emitir_sdk_token)

# ==================== AUTH DO DASHBOARD DO CLIENTE ====================
# Blueprint `/api/cliente/auth` com login humano (cookie HttpOnly) para
# acessar o dashboard de metricas em /cliente/metricas/*.
# Referencia: ark/docs/dashboard-cliente.md
from auth.clientes_users_repo import obter_repo as obter_clientes_users_repo  # noqa: E402
from auth.grafana_sync import criar_servico_se_configurado as criar_grafana_sync  # noqa: E402
from auth.sessao_service import SessaoService  # noqa: E402
from auth import cliente_routes as _cliente_routes_mod  # noqa: E402

try:
    _clientes_users_repo = obter_clientes_users_repo(app.config["TENANTS_DATABASE_URL"])
    _sessao_service = SessaoService(_clientes_users_repo)
    _grafana_sync_service = criar_grafana_sync()  # None se env incompleto
    _cliente_routes_mod.configurar(
        _sessao_service,
        grafana_sync=_grafana_sync_service,
        tenants_repo=_tenants_repo_singleton,
        clientes_users_repo=_clientes_users_repo,
    )
    app.register_blueprint(_cliente_routes_mod.cliente_auth_bp)
    # /cliente/auth/gate e endpoint interno chamado pelo nginx auth_request
    # a cada request de Grafana embed (assets, datasources, etc). Sob default
    # rate limit (50/hour), bate 429 em segundos quando user navega no
    # dashboard — e nginx auth_request interpreta 429 como erro de servidor,
    # devolvendo 500 pro browser. Como /gate so e alcancavel via nginx interno
    # (location internal), nao da pra abusar de fora; isentar do limiter.
    limiter.exempt(_cliente_routes_mod.gate)
    # Endpoints de auth humana ganham limite per-IP no Flask alem do nginx —
    # defesa em profundidade contra brute force. Burst no nginx (5) cobre
    # tentativas rapidas; flask cobre acumulado por minuto.
    limiter.limit("10 per minute")(_cliente_routes_mod.login)
    limiter.limit("5 per minute")(_cliente_routes_mod.solicitar_magic_link)
    limiter.limit("5 per minute")(_cliente_routes_mod.cadastro)
    if _grafana_sync_service:
        log_safe(security_logger, 'info', "[SUCCESS] Grafana org sync ativo")
    log_safe(security_logger, 'info', "[SUCCESS] Auth do dashboard inicializado")
except Exception as e:
    log_safe(security_logger, 'error', f"[ERROR] Falha ao inicializar auth do dashboard: {str(e)}")
    raise

# ==================== EMBED IFRAME ====================
# Blueprint /embed — token curto + serving de dados pra widget React em
# embed.dsplayground.com.br. Reusa cookie cliente_session pra emitir,
# Bearer token RS256 pra ler dados. Ver ark/docs/embed-iframe.md.
try:
    from auth.embed_jwt_service import EmbedJwtService  # noqa: E402
    from embed_routes import configurar as _configurar_embed  # noqa: E402
    from embed_routes import embed_bp as _embed_bp  # noqa: E402

    _embed_jwt_service = EmbedJwtService(keys_dir=app.config['JWT_KEYS_DIR'])
    _configurar_embed(
        embed_jwt_service=_embed_jwt_service,
        sessao_service=_sessao_service,
        tenants_repo=_tenants_repo_singleton,
        influx_service=influxdb_service,
        graficos_permitidos=("eventos_por_minuto",),
    )
    app.register_blueprint(_embed_bp)
    log_safe(security_logger, 'info', "[SUCCESS] Embed iframe inicializado")
except Exception as e:
    log_safe(security_logger, 'error', f"[ERROR] Falha ao inicializar embed: {str(e)}")
    raise

# ==================== BILLING (Stripe webhook + rotas publicas) ====================
# Blueprint /billing — recebe webhooks do Stripe para upgrade/downgrade de plano.
# Requer STRIPE_WEBHOOK_SECRET no env. Sem o env, endpoint responde 501.
try:
    from billing.stripe_webhook import billing_bp as _billing_bp  # noqa: E402
    app.register_blueprint(_billing_bp)
    log_safe(security_logger, 'info', "[SUCCESS] Billing webhook inicializado em /billing/stripe/webhook")
except Exception as e:
    log_safe(security_logger, 'warning', f"[WARNING] Falha ao inicializar billing: {str(e)}")

# Blueprint de rotas publicas de billing (GET /billing/planos — sem auth).
try:
    from billing.routes import billing_routes_bp as _billing_routes_bp  # noqa: E402
    app.register_blueprint(_billing_routes_bp)
    log_safe(security_logger, 'info', "[SUCCESS] Billing routes inicializado em /billing/planos")
except Exception as e:
    log_safe(security_logger, 'warning', f"[WARNING] Falha ao inicializar billing routes: {str(e)}")

# ==================== EXPORTACAO DE ARQUIVOS R2 (cliente) ====================
# Blueprint `/cliente/exportar` — listagem + download via signed URL R2.
# Best-effort: se R2 nao estiver configurado (env vazio), bp nao registra.
try:
    _r2_account_id = (os.environ.get('R2_ACCOUNT_ID') or '').strip()
    _r2_access_key = (os.environ.get('R2_ACCESS_KEY_ID') or '').strip()
    _r2_secret_key = (os.environ.get('R2_SECRET_ACCESS_KEY') or '').strip()
    _r2_bucket = (os.environ.get('R2_BUCKET') or '').strip()
    if all([_r2_account_id, _r2_access_key, _r2_secret_key, _r2_bucket]):
        from archiver.r2_client import R2Client  # noqa: E402
        from archiver import routes as _archiver_routes_mod  # noqa: E402
        _r2_client_singleton = R2Client(
            access_key_id=_r2_access_key,
            secret_access_key=_r2_secret_key,
            bucket=_r2_bucket,
            endpoint_url=R2Client.endpoint_padrao_r2(_r2_account_id),
        )
        _archiver_routes_mod.configurar(
            svc=_sessao_service,
            tenants_repo=_tenants_repo_singleton,
            r2_client=_r2_client_singleton,
        )
        app.register_blueprint(_archiver_routes_mod.cliente_export_bp)
        log_safe(security_logger, 'info', "[SUCCESS] Exportacao R2 inicializada")
    else:
        log_safe(security_logger, 'info',
                 "[INFO] R2 nao configurado (env vazio), /cliente/exportar desabilitado")
except Exception as e:
    log_safe(security_logger, 'warning',
             f"[WARNING] Falha ao inicializar exportacao R2: {str(e)}")

# ==================== ROTAS COM BLUEPRINT ====================

@api_bp.route("/", methods=["GET"])
@limiter.limit("10 per minute")
def index():
    return jsonify({
        "message": "API do Portfólio está funcionando!",
        "security": "enabled",
        "timestamp": datetime.now().isoformat(),
        "influxdb_status": "connected" if influxdb_service else "disconnected",
        "environment": env,
        "context": "api" if env == 'production' else "root"
    })

@api_bp.route("/health", methods=["GET"])
@limiter.limit("30 per minute")
def health_check():
    """Resumo agregado. Mantem formato anterior para compat."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "security": "enabled",
        "active_sessions": len(active_sessions),
        "influxdb": "connected" if (influxdb_service and _influxdb_saudavel()) else "disconnected"
    })


def _influxdb_saudavel() -> bool:
    if not influxdb_service:
        return False
    try:
        return bool(influxdb_service.is_healthy())
    except Exception:
        return False


@api_bp.route("/health/app", methods=["GET"])
@limiter.limit("60 per minute")
def health_app():
    # `ambiente` no payload e o sinal canonico de FLASK_ENV — usado pelo
    # workflow prod-regression pra detectar quando dev server voltou a rodar
    # em producao. Antes esse check era feito via presenca/ausencia do
    # prefixo /api/ na URL, mas o prefixo deixou de variar entre ambientes.
    return jsonify({
        "status": "healthy",
        "detalhe": {
            "timestamp": datetime.now().isoformat(),
            "active_sessions": len(active_sessions),
            "ambiente": env,
        },
    })


@api_bp.route("/health/socketio", methods=["GET"])
@limiter.limit("60 per minute")
def health_socketio():
    # Se a aplicacao responde e o socketio foi inicializado, considera saudavel.
    return jsonify({
        "status": "healthy" if socketio is not None else "unavailable",
        "detalhe": {"conexoes_ativas": len(active_sessions)},
    })


@api_bp.route("/health/influxdb", methods=["GET"])
@limiter.limit("60 per minute")
def health_influxdb():
    if influxdb_service is None:
        return jsonify({
            "status": "unavailable",
            "detalhe": "InfluxDB service nao inicializado",
        }), 503

    if _influxdb_saudavel():
        url = getattr(influxdb_service, 'url', None)
        return jsonify({
            "status": "healthy",
            "detalhe": {"url": url if isinstance(url, str) else None},
        })

    return jsonify({
        "status": "degraded",
        "detalhe": "InfluxDB configurado mas is_healthy() retornou False",
    }), 503

@api_bp.route("/analytics/security/status", methods=["GET"])
@limiter.limit("5 per minute")
@security_middleware
def get_security_status():
    try:
        current_time = time.time()
        active_count = len([s for s in active_sessions.values() 
                           if current_time - s.get('last_activity', 0) < 300])
        suspicious_count = len(suspicious_ips)
        
        security_stats = {
            "active_sessions": active_count,
            "total_sessions_created": len(active_sessions),
            "suspicious_ips_blocked": suspicious_count,
            "security_events_last_hour": len([
                event for event in temporal_stats_cache.get("security_events", [])
                if current_time - event.get('timestamp', 0) < 3600
            ]),
            "timestamp": datetime.now().isoformat(),
            "security_level": "high",
            "protections_enabled": [
                "session_validation", "rate_limiting", "fingerprinting",
                "ip_blocking", "csrf_protection"
            ]
        }
        
        return jsonify({"status": "success", "security": security_stats}), 200
        
    except Exception as e:
        log_safe(security_logger, 'error', f"[ERROR] Erro ao obter status seguranca: {str(e)}")
        return jsonify({"error": "Erro interno do servidor"}), 500

@api_bp.route("/analytics/stats/temporal", methods=["GET"])
@limiter.limit("10 per minute")
@security_middleware
def get_temporal_statistics():
    try:
        cleanup_temporal_cache()
        return jsonify({
            "status": "success",
            "temporal_stats": {
                "total_sessions": temporal_stats_cache["total_sessions"],
                "active_sessions_count": len(temporal_stats_cache["active_sessions"]),
                "cache_size": sum(len(data) for data in temporal_stats_cache["realtime_data"].values()),
                "last_cleanup": temporal_stats_cache["last_cleanup"],
            },
            "timestamp": datetime.now().isoformat()
        }), 200
    except Exception as e:
        log_safe(security_logger, 'error', f"[ERROR] Erro ao obter estatisticas temporais: {str(e)}")
        return jsonify({"error": "Erro interno do servidor"}), 500


def _parametros_consulta_comuns():
    """Extrai os parametros de filtro usados em todos os endpoints de query."""
    app_id = request.args.get('app_id')
    page_type = request.args.get('page_type')
    ambiente = request.args.get('ambiente')
    inicio = request.args.get('inicio', '-24h')
    fim = request.args.get('fim', 'now()')
    try:
        limit = int(request.args.get('limit', '100'))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 1000))
    return {
        'app_id': app_id,
        'page_type': page_type,
        'ambiente': ambiente,
        'inicio': inicio,
        'fim': fim,
        'limit': limit,
    }


def _resolver_site_do_cookie():
    """Valida cookie `cliente_session` e devolve (site_id, bucket_name).

    Retorna (None, None) quando cookie ausente, invalido, expirado, revogado
    ou usuario inativo. Resposta 401 deve ser feita pelo caller.
    """
    from auth import cliente_routes as _cr_mod
    cookie = request.cookies.get(_cr_mod.COOKIE_NAME, "")
    if not cookie:
        return None, None
    user = _cr_mod._obter_svc().validar_cookie(cookie)  # noqa: SLF001
    if user is None:
        return None, None
    # bucket vem de tenants_repo (mesmo singleton injetado em cliente_routes)
    repo = _cr_mod._tenants_repo  # noqa: SLF001
    if repo is None:
        return user.site_id, None
    site = repo.obter_site(user.site_id)
    bucket = site.bucket_name if site else None
    return user.site_id, bucket


@api_bp.route("/analytics/metricas", methods=["GET"])
@limiter.limit("30 per minute")
@security_middleware
def get_analytics_metricas():
    """Soma contadores agregados de `page_analytics` por pagina e periodo.

    Auth obrigatoria via cookie `cliente_session`. Bucket e SEMPRE forcado
    pelo site_id do cookie — querystring `app_id` nao consegue ler dados
    de outro site (isolamento multi-tenant).
    """
    site_id, bucket = _resolver_site_do_cookie()
    if site_id is None:
        return jsonify({"status": "error", "code": "NAO_AUTENTICADO"}), 401

    if not influxdb_service:
        return jsonify({"status": "unavailable", "detalhe": "InfluxDB nao inicializado"}), 503

    params = _parametros_consulta_comuns()
    pontos = influxdb_service.query_metricas_agregadas(**params, bucket=bucket)
    return jsonify({
        "status": "success",
        "filtros": {**params, "site_id": site_id},
        "pontos": pontos,
    })


@api_bp.route("/analytics/web-vitals", methods=["GET"])
@limiter.limit("30 per minute")
@security_middleware
def get_analytics_web_vitals():
    """Lista pontos de Web Vitals (LCP/CLS/INP). Auth via cookie + bucket forcado."""
    site_id, bucket = _resolver_site_do_cookie()
    if site_id is None:
        return jsonify({"status": "error", "code": "NAO_AUTENTICADO"}), 401

    if not influxdb_service:
        return jsonify({"status": "unavailable"}), 503

    params = _parametros_consulta_comuns()
    nome = request.args.get('nome')
    pontos = influxdb_service.query_web_vitals(
        app_id=params['app_id'],
        page_type=params['page_type'],
        nome=nome,
        inicio=params['inicio'],
        fim=params['fim'],
        limit=params['limit'],
        bucket=bucket,
    )
    return jsonify({
        "status": "success",
        "filtros": {**params, "site_id": site_id, "nome": nome},
        "pontos": pontos,
    })


@api_bp.route("/analytics/custom-events", methods=["GET"])
@limiter.limit("30 per minute")
@security_middleware
def get_analytics_custom_events():
    """Soma ocorrencias de eventos customizados. Auth via cookie + bucket forcado."""
    site_id, bucket = _resolver_site_do_cookie()
    if site_id is None:
        return jsonify({"status": "error", "code": "NAO_AUTENTICADO"}), 401

    if not influxdb_service:
        return jsonify({"status": "unavailable"}), 503

    params = _parametros_consulta_comuns()
    nome = request.args.get('nome')
    pontos = influxdb_service.query_custom_events(
        app_id=params['app_id'],
        nome=nome,
        page_type=params['page_type'],
        inicio=params['inicio'],
        fim=params['fim'],
        limit=params['limit'],
        bucket=bucket,
    )
    return jsonify({
        "status": "success",
        "filtros": {**params, "site_id": site_id, "nome": nome},
        "pontos": pontos,
    })


# ==================== LGPD — ADMIN ====================


def _verificar_token_admin():
    token_esperado = os.environ.get('ADMIN_API_TOKEN')
    if not token_esperado:
        return False, "ADMIN_API_TOKEN nao configurado"
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return False, "Header Authorization: Bearer <token> ausente"
    token = header[len('Bearer '):].strip()
    if not hmac.compare_digest(token, token_esperado):
        return False, "Token invalido"
    return True, None


def _fingerprint_admin_token() -> str:
    """SHA-256 truncado do ADMIN_API_TOKEN — fingerprint pra audit log.

    Logar o token cru abriria leak; logar SHA permite correlacao entre eventos
    e detectar uso de token leaked sem expor o segredo. Truncado em 12 chars
    pra reduzir custo no log mantendo unicidade pratica.
    """
    token_esperado = os.environ.get('ADMIN_API_TOKEN', '')
    if not token_esperado:
        return 'no-token'
    return hashlib.sha256(token_esperado.encode()).hexdigest()[:12]


def _registrar_audit(acao: str, session_id: str, resultado: str):
    """Grava linha de auditoria administrativa.

    Inclui fingerprint do token usado pra correlacao em caso de leak suspeito,
    sem expor o token. session_id passa por sanitize basica pra evitar log
    injection (newlines no path).
    """
    sid_safe = (session_id or '')[:128].replace('\n', '\\n').replace('\r', '\\r')
    log_safe(security_logger, 'info',
             f"[ADMIN-AUDIT] acao={acao} session_id={sid_safe} "
             f"resultado={resultado} ip={request.environ.get('REMOTE_ADDR', 'unknown')} "
             f"token_fp={_fingerprint_admin_token()} "
             f"timestamp={datetime.now().isoformat()}")


@api_bp.route("/admin/analytics/sessao/<session_id>", methods=["GET"])
@limiter.limit("60 per minute")
def admin_sessao_consultar(session_id):
    """LGPD — acesso: retorna todos os pontos de uma sessao."""
    ok, motivo = _verificar_token_admin()
    if not ok:
        _registrar_audit('consultar', session_id, f'auth_falhou:{motivo}')
        return jsonify({"status": "error", "code": "UNAUTHORIZED", "message": motivo}), 401

    if not influxdb_service:
        return jsonify({"status": "unavailable"}), 503

    dados = influxdb_service.consultar_por_session_id(session_id)
    _registrar_audit('consultar', session_id, 'ok')
    return jsonify({
        "status": "success",
        "session_id": session_id,
        "dados": dados,
    })


@api_bp.route("/admin/analytics/sessao/<session_id>", methods=["DELETE"])
@limiter.limit("20 per minute")
def admin_sessao_apagar(session_id):
    """LGPD — exclusao: apaga todos os pontos de uma sessao em todos os measurements."""
    ok, motivo = _verificar_token_admin()
    if not ok:
        _registrar_audit('apagar', session_id, f'auth_falhou:{motivo}')
        return jsonify({"status": "error", "code": "UNAUTHORIZED", "message": motivo}), 401

    if not influxdb_service:
        _registrar_audit('apagar', session_id, 'falha_influxdb_ausente')
        return jsonify({"status": "unavailable"}), 503

    sucesso = influxdb_service.apagar_por_session_id(session_id)
    _registrar_audit('apagar', session_id, 'ok' if sucesso else 'falha')
    return jsonify({
        "status": "success" if sucesso else "partial",
        "session_id": session_id,
        "apagado": sucesso,
    })


@api_bp.route("/admin/embed/revogar", methods=["POST"])
@limiter.limit("20 per minute")
def admin_embed_revogar():
    """Revoga um jti de embed JWT — completa item A5 da auditoria.

    Body JSON: {"jti": "<uuid>", "motivo": "<texto opcional>"}
    Idempotente: ON CONFLICT DO NOTHING. Verificacao em /embed/dados ja
    consulta `embed_jwt_revogados`, entao revogacao e instantanea.
    """
    ok, motivo_auth = _verificar_token_admin()
    if not ok:
        _registrar_audit('embed_revogar', '', f'auth_falhou:{motivo_auth}')
        return jsonify({"status": "error", "code": "UNAUTHORIZED", "message": motivo_auth}), 401

    body = request.get_json(silent=True) or {}
    jti = (body.get('jti') or '').strip()
    motivo = (body.get('motivo') or '').strip() or None

    if not jti or len(jti) > 64:
        _registrar_audit('embed_revogar', jti, 'jti_invalido')
        return jsonify({"status": "error", "code": "BAD_REQUEST",
                        "message": "campo `jti` obrigatorio (1..64 chars)"}), 400

    try:
        _tenants_repo_singleton.revogar_jti_embed(jti, motivo=motivo)
    except Exception as erro:
        _registrar_audit('embed_revogar', jti, f'erro_repo:{type(erro).__name__}')
        return jsonify({"status": "error", "code": "INTERNAL"}), 500

    _registrar_audit('embed_revogar', jti, f'ok motivo={motivo or "-"}')
    return jsonify({"status": "success", "jti": jti, "revogado": True})


@api_bp.route("/admin/embed/housekeeping", methods=["POST"])
@limiter.limit("6 per minute")
def admin_embed_housekeeping():
    """Apaga linhas antigas de embed_jwt_revogados (default >48h).

    Body JSON: {"retencao_horas": 48}  (opcional, range 24..720).
    Pode ser chamado por systemd timer no host pra rodar diariamente:

      curl -X POST -H "Authorization: Bearer $ADMIN_API_TOKEN" \\
           https://api.dsplayground.com.br/admin/embed/housekeeping

    No boot do backend ja roda 1x best-effort.
    """
    ok, motivo_auth = _verificar_token_admin()
    if not ok:
        _registrar_audit('embed_housekeeping', '', f'auth_falhou:{motivo_auth}')
        return jsonify({"status": "error", "code": "UNAUTHORIZED", "message": motivo_auth}), 401

    body = request.get_json(silent=True) or {}
    retencao = body.get('retencao_horas', 48)
    try:
        retencao = int(retencao)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "code": "BAD_REQUEST",
                        "message": "retencao_horas deve ser inteiro"}), 400
    if not (24 <= retencao <= 720):
        return jsonify({"status": "error", "code": "BAD_REQUEST",
                        "message": "retencao_horas deve estar entre 24 e 720"}), 400

    try:
        apagados = _tenants_repo_singleton.purgar_embed_jwt_revogados_antigos(
            retencao_horas=retencao,
        )
    except Exception as erro:
        _registrar_audit('embed_housekeeping', '', f'erro_repo:{type(erro).__name__}')
        return jsonify({"status": "error", "code": "INTERNAL"}), 500

    _registrar_audit('embed_housekeeping', '', f'ok apagados={apagados} retencao_h={retencao}')
    return jsonify({"status": "success", "apagados": apagados, "retencao_horas": retencao})


# ✅ REGISTRAR BLUEPRINT
app.register_blueprint(api_bp)

# ==================== WEBSOCKET EVENTS ====================

@socketio.on("connect")
def handle_connect(auth=None):
    session_id = request.sid
    ip_address = request.environ.get('REMOTE_ADDR', 'unknown')
    user_agent = request.headers.get('User-Agent', 'unknown')
    origin = normalizar_origin(request.headers.get('Origin') or request.environ.get('HTTP_ORIGIN'))

    if not check_suspicious_activity(session_id, request):
        log_safe(security_logger, 'warning', f"[BLOCKED] Conexao WebSocket negada para IP suspeito: {ip_address}")
        disconnect()
        return

    # Validacao do sdk_jwt (quando presente ou quando obrigatorio).
    token = None
    if isinstance(auth, dict):
        token = auth.get('token')

    auth_claims = None
    site_id_auth = None

    if token:
        try:
            auth_claims = validar_token_socketio(token, scope_esperado='ingest')
        except AuthError as err:
            log_safe(security_logger, 'warning',
                     f"[SECURITY] handshake rejeitado code={err.code} ip={ip_address}")
            disconnect()
            return

        # Defesa em profundidade: revalida Origin contra allowlist do site.
        repo = obter_tenants_repo()
        if origin is None or not repo.origin_permitido(auth_claims.site_id, origin):
            log_safe(security_logger, 'warning',
                     f"[SECURITY] handshake rejeitado code=ORIGIN_NOT_ALLOWED site={auth_claims.site_id} origin={origin}")
            disconnect()
            return

        site_id_auth = auth_claims.site_id
    elif app.config.get('SDK_AUTH_REQUIRED', False):
        log_safe(security_logger, 'warning',
                 f"[SECURITY] handshake rejeitado code=TOKEN_MISSING ip={ip_address}")
        disconnect()
        return

    fingerprint = create_session_fingerprint(request)
    session_token = generate_session_token()

    active_sessions[session_id] = {
        'token': session_token, 'fingerprint': fingerprint,
        'ip_address': ip_address, 'user_agent': user_agent,
        'created_at': time.time(), 'last_activity': time.time(), 'request_count': 0,
        'site_id': site_id_auth,
        'app_id': auth_claims.app_id if auth_claims else None,
        'ambiente': auth_claims.ambiente if auth_claims else None,
        'scope': auth_claims.scope if auth_claims else None,
        'jwt_exp': auth_claims.exp if auth_claims else None,
        'origin': origin,
    }

    log_safe(security_logger, 'info',
             f"evento=conectado session_id={session_id} ip={ip_address} site={site_id_auth or '-'}")

    # Onda 1 — resync pos-reconnect: se o cliente passar analytics_session_id no
    # handshake, devolvemos o ultimo id_registro aceito para aquela sessao logica,
    # permitindo ao SDK descartar itens da fila ja processados.
    analytics_session_id = None
    schema_cliente = None
    if isinstance(auth, dict):
        analytics_session_id = auth.get('analytics_session_id')
        schema_cliente = auth.get('schema_version')
    last_id = last_at = None
    if analytics_session_id:
        from ingestao.idempotencia import obter_registro_ultimo
        last_id, last_at = obter_registro_ultimo().obter(analytics_session_id)

    # Onda 3 — negociacao de schema version no handshake Socket.IO.
    from auth.routes import SCHEMA_VERSION_SERVIDOR, SCHEMA_VERSION_MINIMO_CLIENTE, _versao_menor_que
    schema_incompativel = (
        schema_cliente is not None
        and _versao_menor_que(schema_cliente, SCHEMA_VERSION_MINIMO_CLIENTE)
    )
    if schema_incompativel:
        log_safe(security_logger, 'warning',
                 f"[SECURITY] handshake rejeitado code=UNSUPPORTED_SCHEMA "
                 f"schema_cliente={schema_cliente} minimo={SCHEMA_VERSION_MINIMO_CLIENTE}")
        emit("schema_error", {
            "code": "UNSUPPORTED_SCHEMA",
            "message": f"Schema {schema_cliente} inferior ao minimo {SCHEMA_VERSION_MINIMO_CLIENTE}",
            "server_schema_version": SCHEMA_VERSION_SERVIDOR,
            "min_client_schema": SCHEMA_VERSION_MINIMO_CLIENTE,
        })
        disconnect()
        return

    emit("connection_response", {
        "status": "connected",
        "session_token": session_token,
        "site_id": site_id_auth,
        "authenticated": auth_claims is not None,
        "timestamp": datetime.now().isoformat(),
        "server_time": int(time.time() * 1000),
        "last_received_id_registro": last_id,
        "last_received_at": last_at,
        "security_level": "high" if auth_claims else "legacy",
        "server_schema_version": SCHEMA_VERSION_SERVIDOR,
        "min_client_schema": SCHEMA_VERSION_MINIMO_CLIENTE,
    })

@socketio.on("disconnect")
def handle_disconnect():
    session_id = request.sid
    if session_id in active_sessions:
        session_data = active_sessions[session_id]
        duration = time.time() - session_data.get('created_at', 0)
        log_safe(security_logger, 'info',
                 f"evento=desconectado session_id={session_id} duracao_s={duration:.1f}")
        del active_sessions[session_id]
    if session_id in temporal_stats_cache["active_sessions"]:
        del temporal_stats_cache["active_sessions"][session_id]


# Background reaper de sessoes zombies. Roda a cada 30s, remove sessoes
# sem atividade ha > SESSION_IDLE_TIMEOUT segundos. handle_disconnect ja
# limpa quando o evento dispara, mas em casos de network drop/queda
# abrupta o evento nem sempre chega — sem isso o dict acumula zombies
# (cleanup_temporal_cache so roda dentro de handle_analytics_data, que
# nao dispara em sessoes inativas).
SESSION_IDLE_TIMEOUT = int(os.environ.get('SESSION_IDLE_TIMEOUT', '180'))   # 3 min
SESSION_REAPER_INTERVAL = int(os.environ.get('SESSION_REAPER_INTERVAL', '30'))


def _reaper_de_sessoes():
    while True:
        socketio.sleep(SESSION_REAPER_INTERVAL)
        agora = time.time()
        zombies = [
            sid for sid, data in list(active_sessions.items())
            if agora - data.get('last_activity', data.get('created_at', agora)) > SESSION_IDLE_TIMEOUT
        ]
        if zombies:
            for sid in zombies:
                active_sessions.pop(sid, None)
                temporal_stats_cache["active_sessions"].pop(sid, None)
            log_safe(security_logger, 'info',
                     f"[REAPER] removidas {len(zombies)} sessoes zombies (idle > {SESSION_IDLE_TIMEOUT}s)")


socketio.start_background_task(_reaper_de_sessoes)

@socketio.on("analytics_data")
@security_middleware
def handle_analytics_data(data):
    try:
        session_id = request.sid

        if not validate_session_integrity(session_id, request):
            log_safe(security_logger, 'warning', f"[SECURITY] Sessao invalida tentando enviar dados: {session_id}")
            emit("analytics_error", {"status": "error", "code": "INVALID_SESSION", "message": "Sessao invalida"})
            disconnect()
            return

        active_sessions[session_id]['last_activity'] = time.time()
        active_sessions[session_id]['request_count'] += 1

        # Limite total de batches por sessao. SDK envia 1 batch a cada
        # `intervaloEnvioMs` (default 5s = 12/min). Em 1h normal de navegacao
        # sao ~720 batches; em sessoes muito longas (varias horas), bumpar
        # pra mais via ENV. Valor zerado/negativo desabilita o limite.
        teto = int(app.config.get('SESSION_REQUEST_LIMIT', 10000))
        if teto > 0 and active_sessions[session_id]['request_count'] > teto:
            log_safe(security_logger, 'warning',
                     f"[WARNING] Rate limit de sessao excedido: {session_id} "
                     f"({active_sessions[session_id]['request_count']} > {teto})")
            emit("analytics_error", {"status": "error", "code": "RATE_LIMIT", "message": "Rate limit excedido"})
            return

        cleanup_temporal_cache()

        if not data:
            emit("analytics_error", {"status": "error", "code": "EMPTY_PAYLOAD", "message": "Nenhum dado foi enviado"})
            return

        user_agent = request.headers.get('User-Agent', 'unknown')
        ip_address = request.environ.get('REMOTE_ADDR', 'unknown')
        # Sprint 2 bloco B - tags derivadas server-side. Headers vem do
        # handshake Socket.IO original; em prod, Cloudflare injeta CF-IPCountry.
        referer = request.headers.get('Referer')
        cf_ipcountry = request.headers.get('CF-IPCountry')

        site_id_ativo = active_sessions[session_id].get('site_id')
        resumo = servico_ingestao.ingerir(
            session_id=session_id,
            data=data,
            user_agent=user_agent,
            ip_address=ip_address,
            site_id=site_id_ativo,
            referer=referer,
            cf_ipcountry=cf_ipcountry,
        )

        if resumo.status == 'success':
            temporal_stats_cache["total_sessions"] += 1
            temporal_stats_cache["active_sessions"][session_id] = {
                "last_update": datetime.now().isoformat(),
                "id_registro": resumo.id_registro,
                "security_validated": True,
                "ip_address": active_sessions[session_id]['ip_address'],
            }

            log_safe(security_logger, 'info',
                     f"[ANALYTICS] validado session={session_id} id_registro={resumo.id_registro}")
            emit("analytics_received", resumo.to_dict())
        else:
            log_safe(security_logger, 'warning',
                     f"[ANALYTICS] rejeitado session={session_id} erros={resumo.erros}")
            emit("analytics_error", resumo.to_dict())

    except Exception as e:
        log_safe(security_logger, 'error', f"[ERROR] Erro interno analytics de {session_id}: {str(e)}")
        emit("analytics_error", {"status": "error", "code": "INTERNAL_ERROR", "message": "Erro interno do servidor"})

# ==================== EMAIL DIÁRIO DE REJEIÇÕES ====================
# Roda uma vez por dia às 06:00 UTC. Envia resumo de QUOTA_EXCEDIDA e
# CARDINALIDADE_EXCEDIDA para os admins de cada site afetado.
# Fonte dos contadores: ingestao.rejeicoes_diarias (in-memory, reset após envio).

def _segundos_ate_proxima_hora_utc(hora_alvo: int) -> float:
    """Segundos até a próxima ocorrência de hora_alvo:00:00 UTC."""
    from datetime import datetime, timezone
    agora = datetime.now(timezone.utc)
    proxima = agora.replace(hour=hora_alvo, minute=0, second=0, microsecond=0)
    if proxima <= agora:
        from datetime import timedelta
        proxima += timedelta(days=1)
    return (proxima - agora).total_seconds()


def _enviar_email_rejeicoes(site_id: str, contagens: dict) -> None:
    """Envia email de resumo de rejeições para os admins do site."""
    try:
        emails = _clientes_users_repo.listar_emails_admin_por_site(site_id)
    except Exception as e:
        log_safe(security_logger, 'warning',
                 f"[EMAILER] falha ao buscar admins site_id={site_id} erro={e}")
        return

    if not emails:
        return

    site = None
    try:
        site = _tenants_repo_singleton.obter_site(site_id)
    except Exception:
        pass

    nome_site = site.nome if site else site_id
    landing = os.environ.get("LANDING_BASE_URL", "https://dsplayground.com.br")
    dashboard = os.environ.get("DASHBOARD_REDIRECT", f"{landing}/cliente/metricas")

    quota_count = contagens.get("QUOTA_EXCEDIDA", 0)
    card_count = contagens.get("CARDINALIDADE_EXCEDIDA", 0)
    total = quota_count + card_count

    corpo_texto = (
        f"Relatório diário de eventos rejeitados — {nome_site}\n\n"
        f"No último período, {total} evento(s) foram rejeitados pelo servidor:\n\n"
        + (f"  • Cota diária excedida:        {quota_count} evento(s)\n" if quota_count else "")
        + (f"  • Cardinalidade excedida:      {card_count} evento(s)\n" if card_count else "")
        + f"\nIsso não afeta os dados já coletados — apenas os eventos acima\n"
        f"foram descartados porque o limite do plano atual foi atingido.\n\n"
        f"O QUE FAZER\n"
        f"Acesse seu dashboard para verificar o consumo atual:\n"
        f"{dashboard}\n\n"
        f"Para aumentar sua cota ou cardinalidade, faça upgrade do plano em:\n"
        f"{landing}/cliente/configuracoes?tab=faturamento\n\n"
        f"Este resumo é enviado uma vez por dia, apenas quando há rejeições.\n\n"
        f"Atenciosamente,\n"
        f"Equipe DSPlayground Analytics\n"
        f"dsplayground.com.br\n"
    )

    from auth.email_sender import criar_sender_padrao as _criar_sender
    sender = _criar_sender()
    for email in emails:
        try:
            sender.enviar(
                destinatario=email,
                assunto=f"[DSPlayground] {total} evento(s) rejeitado(s) hoje — {nome_site}",
                corpo_texto=corpo_texto,
            )
        except Exception as e:
            log_safe(security_logger, 'warning',
                     f"[EMAILER] falha ao enviar rejeicoes site_id={site_id} email={email} erro={e}")


def _emailer_rejeicoes_diarias():
    """Background task: envia emails de rejeição 1×/dia às 06:00 UTC."""
    from ingestao.rejeicoes_diarias import obter_contador as _obter_contador
    hora_envio = int(os.environ.get("EMAILER_REJEICOES_HORA_UTC", "6"))

    while True:
        espera = _segundos_ate_proxima_hora_utc(hora_envio)
        socketio.sleep(espera)

        snapshot = _obter_contador().obter_e_resetar()
        if not snapshot:
            continue

        log_safe(security_logger, 'info',
                 f"[EMAILER] rodando rejeicoes_diarias sites={len(snapshot)}")
        for site_id, contagens in snapshot.items():
            _enviar_email_rejeicoes(site_id, contagens)


socketio.start_background_task(_emailer_rejeicoes_diarias)
log_safe(security_logger, 'info', "[SUCCESS] Emailer de rejeicoes diarias iniciado (06:00 UTC)")


# ==================== INICIALIZAÇÃO ====================

if __name__ == "__main__":
    if env == 'production':
        log_safe(security_logger, 'info', "[CONFIG] Iniciando servidor em modo PRODUCAO com seguranca maxima")
    else:
        log_safe(security_logger, 'info', "[CONFIG] Iniciando servidor em modo DESENVOLVIMENTO")
    
    socketio.run(
        app, host=app.config.get("HOST", "127.0.0.1"), port=app.config.get("PORT", 5000),
        debug=(env == 'development'),
        allow_unsafe_werkzeug=(env == 'development')
    )
