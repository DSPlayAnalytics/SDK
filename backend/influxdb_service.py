"""Integracao com InfluxDB 2.7.

Responsabilidades:
- Escrever metricas agregadas (`page_analytics`) e Web Vitals individuais (`web_vitals`)
- Escrever eventos customizados (`custom_events`) — um Point por evento
- Expor queries agregadas para a API REST de consulta
- Expor operacoes LGPD (consulta e exclusao por `session_id`)

Semantica: cada tick do SDK e um delta. Contadores somam — dashboards usam `sum()`,
nao `mean()`. `permanencia_segundos` tambem soma (tempo visivel adicional na janela).
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ==================== VALIDADORES (anti-injecao Flux) ====================
#
# Inputs que entram em queries Flux via f-string precisam ser validados antes
# de chegarem aqui. Bucket-per-tenant ja limita o blast radius (ataque preso
# ao bucket do proprio cliente), mas mesmo assim um filtro malicioso pode
# vazar dados de outro user/sessao DENTRO do bucket. Usamos allowlist regex
# em vez de tentar escapar — Flux strings com `\` e `"` exigem cuidado e
# allowlist e mais defensivel.

_RE_TAG_VALOR = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")
_RE_TEMPO = re.compile(
    r"^("                                # absoluto OU relativo OU now()
    r"now\(\)"                            # now()
    r"|-?\d+(ns|us|µs|ms|s|m|h|d|w|y)"   # -24h, -7d, 30m, etc.
    r"|\d{4}-\d{2}-\d{2}"                # YYYY-MM-DD
    r"(T\d{2}:\d{2}:\d{2}(\.\d+)?Z?)?"   # ...THH:MM:SS[.fff][Z] opcional
    r")$"
)
_RE_BUCKET = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
_RE_SESSION_ID = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


class FluxParametroInvalido(ValueError):
    """Erro levantado quando um parametro de query Flux nao passa na allowlist."""


def _validar_tag(nome: str, valor: Optional[str]) -> Optional[str]:
    """Valida valor de tag/field; retorna o valor se OK, None se vazio."""
    if valor is None or valor == "":
        return None
    if not isinstance(valor, str) or not _RE_TAG_VALOR.match(valor):
        raise FluxParametroInvalido(
            f"valor invalido para {nome}: caracteres fora da allowlist"
        )
    return valor


def _validar_tempo(nome: str, valor: str) -> str:
    """Valida expressao temporal Flux (range start/stop)."""
    if not isinstance(valor, str) or not _RE_TEMPO.match(valor):
        raise FluxParametroInvalido(
            f"valor invalido para {nome}: nao e expressao temporal Flux"
        )
    return valor


def _validar_bucket(valor: str) -> str:
    if not isinstance(valor, str) or not _RE_BUCKET.match(valor):
        raise FluxParametroInvalido("bucket invalido")
    return valor


def _validar_session_id(valor: str) -> str:
    if not isinstance(valor, str) or not _RE_SESSION_ID.match(valor):
        raise FluxParametroInvalido("session_id invalido")
    return valor

try:
    from influxdb_client import InfluxDBClient, Point
    from influxdb_client.client.write_api import SYNCHRONOUS
    INFLUXDB_AVAILABLE = True
except ImportError:
    INFLUXDB_AVAILABLE = False
    logging.warning("InfluxDB client nao instalado. Execute: pip install influxdb-client")


@dataclass
class TemporalMetric:
    """Metrica agregada por pagina por tick."""
    session_id: str
    page_type: str
    permanencia_segundos: float
    visualizacoes: int
    cliques: int = 0
    scrolls: int = 0
    mouse_moves: int = 0
    toques: int = 0
    hovers: int = 0
    exposicoes: int = 0
    custom_events: int = 0
    timestamp: Optional[datetime] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    app_id: Optional[str] = None
    ambiente: Optional[str] = None
    device_type: Optional[str] = None
    pais: Optional[str] = None
    referrer_dominio: Optional[str] = None
    # Schema 1.2 (SDK v0.4): identidade de usuario / org.
    # user_bucket / group_bucket viram tag (256 bins, cardinalidade controlada);
    # user_id / group_id viram field (cardinalidade zero, exibicao/JOIN).
    user_id: Optional[str] = None
    user_bucket: Optional[str] = None
    group_id: Optional[str] = None
    group_bucket: Optional[str] = None
    # Tenant trust-anchor: derivado server-side do publishable_key (= site.slug).
    # Diferente de app_id, que vem do SDK e nao serve pra security/RLS.
    site_slug: Optional[str] = None


@dataclass
class WebVitalMetric:
    """Metrica de performance (LCP/CLS/INP) por evento."""
    session_id: str
    page_type: str
    nome: str
    valor: float
    rating: Optional[str] = None
    metric_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    app_id: Optional[str] = None
    ambiente: Optional[str] = None
    device_type: Optional[str] = None
    pais: Optional[str] = None
    referrer_dominio: Optional[str] = None
    user_id: Optional[str] = None
    user_bucket: Optional[str] = None
    group_id: Optional[str] = None
    group_bucket: Optional[str] = None
    site_slug: Optional[str] = None


@dataclass
class CustomEventMetric:
    """Evento de negocio enviado via `enviarEvento(nome, propriedades)`."""
    session_id: str
    page_type: str
    nome: str
    propriedades: Dict[str, Any]
    timestamp: Optional[datetime] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    app_id: Optional[str] = None
    ambiente: Optional[str] = None
    device_type: Optional[str] = None
    pais: Optional[str] = None
    referrer_dominio: Optional[str] = None
    user_id: Optional[str] = None
    user_bucket: Optional[str] = None
    group_id: Optional[str] = None
    group_bucket: Optional[str] = None
    site_slug: Optional[str] = None


@dataclass
class ConversionEventMetric:
    """Evento de conversao comercial (__purchase/__signup/__conversion)."""
    session_id: str
    page_type: str
    nome: str    # nome original: __purchase, __signup, __conversion
    tipo: str    # tipo sem __: purchase, signup, ou subtipo de __conversion
    propriedades: Dict[str, Any]
    valor: Optional[float] = None
    moeda: Optional[str] = None
    plano: Optional[str] = None
    timestamp: Optional[datetime] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    app_id: Optional[str] = None
    ambiente: Optional[str] = None
    device_type: Optional[str] = None
    pais: Optional[str] = None
    referrer_dominio: Optional[str] = None
    user_id: Optional[str] = None
    user_bucket: Optional[str] = None
    group_id: Optional[str] = None
    group_bucket: Optional[str] = None
    site_slug: Optional[str] = None


# Nomes de eventos SDK internos que NAO devem entrar nos pipelines de storage.
_EVENTOS_IDENTIDADE = frozenset({"__identify", "__group", "__reset"})
# Nomes de eventos comerciais: roteados para conversion_events.
_EVENTOS_CONVERSAO = frozenset({"__purchase", "__signup", "__conversion"})


def _aplicar_identidade(point, metric) -> "Point":
    """Aplica tags/fields de identidade (schema 1.2) a um Point ja construido.

    Decisao D1 opcao C:
      - user_bucket / group_bucket -> TAG (256 bins, cardinalidade controlada).
      - user_id / group_id -> FIELD (cardinalidade zero, exibicao/JOIN).
      - site_slug -> TAG (trust-anchor de tenant; resolvido server-side do
        publishable_key, NAO do payload SDK; usado por filtros multi-tenant
        em dashboards Grafana via `r.site_slug == "${__user.login}"`).

    None nao e gravado — preserva forward-compat com Pontos antigos
    (queries Flux com `r.user_bucket` so retornam linhas que tem o tag).
    """
    if metric.user_bucket:
        point = point.tag("user_bucket", metric.user_bucket)
    if metric.group_bucket:
        point = point.tag("group_bucket", metric.group_bucket)
    if metric.user_id:
        point = point.field("user_id", metric.user_id)
    if metric.group_id:
        point = point.field("group_id", metric.group_id)
    if getattr(metric, "site_slug", None):
        point = point.tag("site_slug", metric.site_slug)
    return point


class InfluxDBService:
    def __init__(self, url: str, token: str, org: str, bucket: str, enabled: bool = True,
                 executor_max_workers: int = 2):
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.enabled = enabled and INFLUXDB_AVAILABLE

        self.client = None
        self.write_api = None
        self.executor = ThreadPoolExecutor(max_workers=executor_max_workers)

        if self.enabled:
            self._initialize_client()
        else:
            logging.warning("InfluxDB desabilitado ou cliente nao disponivel")

    def _initialize_client(self):
        try:
            self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org, timeout=5000)
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

            health = self.client.health()
            if health.status == "pass":
                logging.info(f"InfluxDB conectado: {self.url}")
            else:
                logging.error(f"InfluxDB health check falhou: {health.message}")
                self.enabled = False
        except Exception as e:
            logging.error(f"Erro ao conectar InfluxDB: {str(e)}")
            self.enabled = False

    # ==================== ESCRITA ====================

    def write_temporal_metrics(self, metric: TemporalMetric, bucket: Optional[str] = None) -> bool:
        if not self.enabled:
            return False
        try:
            point = (
                Point("page_analytics")
                .tag("session_id", metric.session_id)
                .tag("page_type", metric.page_type)
                .tag("app_id", metric.app_id)
                .tag("ambiente", metric.ambiente)
                .tag("device_type", metric.device_type or "unknown")
                .tag("pais", metric.pais or "unknown")
                .tag("referrer_dominio", metric.referrer_dominio or "direto")
                .field("ip_address", metric.ip_address or "unknown")
                .field("permanencia_segundos", float(metric.permanencia_segundos))
                .field("visualizacoes", int(metric.visualizacoes))
                .field("cliques", int(metric.cliques))
                .field("scrolls", int(metric.scrolls))
                .field("mouse_moves", int(metric.mouse_moves))
                .field("toques", int(metric.toques))
                .field("hovers", int(metric.hovers))
                .field("exposicoes", int(metric.exposicoes))
                .field("custom_events", int(metric.custom_events))
                .field("user_agent", metric.user_agent or "unknown")
                .time(metric.timestamp or datetime.now(timezone.utc))
            )
            point = _aplicar_identidade(point, metric)
            self.write_api.write(bucket=bucket or self.bucket, record=point)
            return True
        except Exception as e:
            logging.error(f"Erro ao escrever page_analytics: {str(e)}")
            return False

    def write_temporal_metrics_async(self, metric: TemporalMetric, bucket: Optional[str] = None):
        if not self.enabled:
            return
        self.executor.submit(lambda: self.write_temporal_metrics(metric, bucket=bucket))

    def write_web_vital(self, metric: WebVitalMetric, bucket: Optional[str] = None) -> bool:
        if not self.enabled:
            return False
        try:
            point = (
                Point("web_vitals")
                .tag("session_id", metric.session_id)
                .tag("page_type", metric.page_type)
                .tag("nome", metric.nome)
                .tag("rating", metric.rating or "unknown")
                .tag("app_id", metric.app_id)
                .tag("ambiente", metric.ambiente)
                .tag("device_type", metric.device_type or "unknown")
                .tag("pais", metric.pais or "unknown")
                .tag("referrer_dominio", metric.referrer_dominio or "direto")
                .field("ip_address", metric.ip_address or "unknown")
                .field("valor", float(metric.valor))
                .field("user_agent", metric.user_agent or "unknown")
                .time(metric.timestamp or datetime.now(timezone.utc))
            )
            if metric.metric_id:
                point = point.field("metric_id", metric.metric_id)
            point = _aplicar_identidade(point, metric)
            self.write_api.write(bucket=bucket or self.bucket, record=point)
            return True
        except Exception as e:
            logging.error(f"Erro ao escrever web_vitals: {str(e)}")
            return False

    def write_web_vital_async(self, metric: WebVitalMetric, bucket: Optional[str] = None):
        if not self.enabled:
            return
        self.executor.submit(lambda: self.write_web_vital(metric, bucket=bucket))

    def write_custom_event(self, metric: CustomEventMetric, bucket: Optional[str] = None) -> bool:
        if not self.enabled:
            return False
        try:
            point = (
                Point("custom_events")
                .tag("session_id", metric.session_id)
                .tag("page_type", metric.page_type)
                .tag("nome", metric.nome)
                .tag("app_id", metric.app_id)
                .tag("ambiente", metric.ambiente)
                .tag("device_type", metric.device_type or "unknown")
                .tag("pais", metric.pais or "unknown")
                .tag("referrer_dominio", metric.referrer_dominio or "direto")
                .field("ip_address", metric.ip_address or "unknown")
                .field("ocorrencias", 1)
                .field("user_agent", metric.user_agent or "unknown")
                .time(metric.timestamp or datetime.now(timezone.utc))
            )
            for chave, valor in (metric.propriedades or {}).items():
                # Apenas primitivos sao aceitos (ja sanitizado pelo SDK)
                chave_sanitizada = f"prop_{chave}"
                if isinstance(valor, bool):
                    point = point.field(chave_sanitizada, valor)
                elif isinstance(valor, (int, float)):
                    point = point.field(chave_sanitizada, float(valor))
                elif isinstance(valor, str):
                    point = point.field(chave_sanitizada, valor)
                # None/outros descartados
            point = _aplicar_identidade(point, metric)
            self.write_api.write(bucket=bucket or self.bucket, record=point)
            return True
        except Exception as e:
            logging.error(f"Erro ao escrever custom_events: {str(e)}")
            return False

    def write_custom_event_async(self, metric: CustomEventMetric, bucket: Optional[str] = None):
        if not self.enabled:
            return
        self.executor.submit(lambda: self.write_custom_event(metric, bucket=bucket))

    def write_conversion_event(self, metric: ConversionEventMetric, bucket: Optional[str] = None) -> bool:
        if not self.enabled:
            return False
        try:
            point = (
                Point("conversion_events")
                .tag("session_id", metric.session_id)
                .tag("page_type", metric.page_type)
                .tag("tipo", metric.tipo)
                .tag("app_id", metric.app_id)
                .tag("ambiente", metric.ambiente)
                .tag("device_type", metric.device_type or "unknown")
                .tag("pais", metric.pais or "unknown")
                .tag("referrer_dominio", metric.referrer_dominio or "direto")
                .field("ip_address", metric.ip_address or "unknown")
                .field("ocorrencias", 1)
                .field("user_agent", metric.user_agent or "unknown")
                .time(metric.timestamp or datetime.now(timezone.utc))
            )
            if metric.valor is not None:
                point = point.field("valor", float(metric.valor))
            if metric.moeda:
                point = point.field("moeda", metric.moeda)
            if metric.plano:
                point = point.field("plano", metric.plano)
            for chave, valor in (metric.propriedades or {}).items():
                chave_sanitizada = f"prop_{chave}"
                if isinstance(valor, bool):
                    point = point.field(chave_sanitizada, valor)
                elif isinstance(valor, (int, float)):
                    point = point.field(chave_sanitizada, float(valor))
                elif isinstance(valor, str):
                    point = point.field(chave_sanitizada, valor)
            point = _aplicar_identidade(point, metric)
            self.write_api.write(bucket=bucket or self.bucket, record=point)
            return True
        except Exception as e:
            logging.error(f"Erro ao escrever conversion_events: {str(e)}")
            return False

    def write_conversion_event_async(self, metric: ConversionEventMetric, bucket: Optional[str] = None):
        if not self.enabled:
            return
        self.executor.submit(lambda: self.write_conversion_event(metric, bucket=bucket))

    # ==================== QUERIES ====================

    def query_metricas_agregadas(
        self,
        app_id: Optional[str] = None,
        page_type: Optional[str] = None,
        ambiente: Optional[str] = None,
        inicio: str = "-24h",
        fim: str = "now()",
        limit: int = 100,
        bucket: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Soma contadores de `page_analytics` por pagina/periodo.

        `bucket` (opcional): se informado, sobrescreve o default `self.bucket`.
        Usado pelo endpoint REST autenticado pra forcar bucket-per-cliente.
        """
        if not self.enabled:
            return []

        app_id = _validar_tag("app_id", app_id)
        page_type = _validar_tag("page_type", page_type)
        ambiente = _validar_tag("ambiente", ambiente)
        inicio = _validar_tempo("inicio", inicio)
        fim = _validar_tempo("fim", fim)
        bucket_alvo = _validar_bucket(bucket or self.bucket)

        filtros = ['r._measurement == "page_analytics"']
        if app_id:
            filtros.append(f'r.app_id == "{app_id}"')
        if page_type:
            filtros.append(f'r.page_type == "{page_type}"')
        if ambiente:
            filtros.append(f'r.ambiente == "{ambiente}"')
        filtro_str = ' and '.join(filtros)

        campos_numericos = [
            "permanencia_segundos", "visualizacoes", "cliques", "scrolls",
            "mouse_moves", "toques", "hovers", "exposicoes", "custom_events",
        ]
        filtro_campos = ' or '.join([f'r._field == "{c}"' for c in campos_numericos])

        query = f'''
        from(bucket: "{bucket_alvo}")
          |> range(start: {inicio}, stop: {fim})
          |> filter(fn: (r) => {filtro_str})
          |> filter(fn: (r) => {filtro_campos})
          |> group(columns: ["page_type", "_field"])
          |> sum()
          |> limit(n: {int(limit)})
        '''
        try:
            resultado = self.client.query_api().query(query=query)
            agregado: Dict[str, Dict[str, float]] = {}
            for tabela in resultado:
                for registro in tabela.records:
                    pagina = registro.values.get('page_type', 'desconhecido')
                    campo = registro.values.get('_field')
                    valor = registro.get_value() or 0
                    if pagina not in agregado:
                        agregado[pagina] = {}
                    agregado[pagina][campo] = valor
            return [{"page_type": k, "totais": v} for k, v in agregado.items()]
        except Exception as e:
            logging.error(f"Erro em query_metricas_agregadas: {str(e)}")
            return []

    def query_web_vitals(
        self,
        app_id: Optional[str] = None,
        page_type: Optional[str] = None,
        nome: Optional[str] = None,
        inicio: str = "-24h",
        fim: str = "now()",
        limit: int = 500,
        bucket: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Lista pontos de Web Vitals com filtros. `bucket` sobrescreve default."""
        if not self.enabled:
            return []

        app_id = _validar_tag("app_id", app_id)
        page_type = _validar_tag("page_type", page_type)
        nome = _validar_tag("nome", nome)
        inicio = _validar_tempo("inicio", inicio)
        fim = _validar_tempo("fim", fim)
        bucket_alvo = _validar_bucket(bucket or self.bucket)

        filtros = ['r._measurement == "web_vitals"', 'r._field == "valor"']
        if app_id:
            filtros.append(f'r.app_id == "{app_id}"')
        if page_type:
            filtros.append(f'r.page_type == "{page_type}"')
        if nome:
            filtros.append(f'r.nome == "{nome}"')
        filtro_str = ' and '.join(filtros)

        query = f'''
        from(bucket: "{bucket_alvo}")
          |> range(start: {inicio}, stop: {fim})
          |> filter(fn: (r) => {filtro_str})
          |> limit(n: {int(limit)})
        '''
        try:
            resultado = self.client.query_api().query(query=query)
            pontos: List[Dict[str, Any]] = []
            for tabela in resultado:
                for registro in tabela.records:
                    pontos.append({
                        "time": registro.get_time().isoformat() if registro.get_time() else None,
                        "nome": registro.values.get('nome'),
                        "page_type": registro.values.get('page_type'),
                        "rating": registro.values.get('rating'),
                        "valor": registro.get_value(),
                    })
            return pontos
        except Exception as e:
            logging.error(f"Erro em query_web_vitals: {str(e)}")
            return []

    def query_custom_events(
        self,
        app_id: Optional[str] = None,
        nome: Optional[str] = None,
        page_type: Optional[str] = None,
        inicio: str = "-24h",
        fim: str = "now()",
        limit: int = 100,
        bucket: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Soma ocorrencias de eventos customizados. `bucket` sobrescreve default."""
        if not self.enabled:
            return []

        filtros = ['r._measurement == "custom_events"', 'r._field == "ocorrencias"']
        if app_id:
            filtros.append(f'r.app_id == "{app_id}"')
        if nome:
            filtros.append(f'r.nome == "{nome}"')
        if page_type:
            filtros.append(f'r.page_type == "{page_type}"')
        filtro_str = ' and '.join(filtros)

        bucket_alvo = bucket or self.bucket
        query = f'''
        from(bucket: "{bucket_alvo}")
          |> range(start: {inicio}, stop: {fim})
          |> filter(fn: (r) => {filtro_str})
          |> group(columns: ["nome", "page_type"])
          |> sum()
          |> limit(n: {int(limit)})
        '''
        try:
            resultado = self.client.query_api().query(query=query)
            contagens: List[Dict[str, Any]] = []
            for tabela in resultado:
                for registro in tabela.records:
                    contagens.append({
                        "nome": registro.values.get('nome'),
                        "page_type": registro.values.get('page_type'),
                        "ocorrencias": int(registro.get_value() or 0),
                    })
            return contagens
        except Exception as e:
            logging.error(f"Erro em query_custom_events: {str(e)}")
            return []

    # ==================== LGPD ====================

    def consultar_por_session_id(self, session_id: str, inicio: str = "-30d") -> Dict[str, List[Dict[str, Any]]]:
        """Retorna todos os pontos de uma sessao (LGPD — acesso)."""
        if not self.enabled:
            return {"page_analytics": [], "web_vitals": [], "custom_events": []}

        session_id = _validar_session_id(session_id)
        inicio = _validar_tempo("inicio", inicio)
        bucket_alvo = _validar_bucket(self.bucket)

        saida: Dict[str, List[Dict[str, Any]]] = {
            "page_analytics": [],
            "web_vitals": [],
            "custom_events": [],
        }

        # Lista hardcoded — measurements nunca vem do request, sao constantes
        # do schema. Mantida fora da allowlist generica pra clareza.
        for measurement in saida.keys():
            query = f'''
            from(bucket: "{bucket_alvo}")
              |> range(start: {inicio})
              |> filter(fn: (r) => r._measurement == "{measurement}")
              |> filter(fn: (r) => r.session_id == "{session_id}")
              |> limit(n: 5000)
            '''
            try:
                resultado = self.client.query_api().query(query=query)
                for tabela in resultado:
                    for registro in tabela.records:
                        saida[measurement].append({
                            "time": registro.get_time().isoformat() if registro.get_time() else None,
                            "field": registro.values.get('_field'),
                            "value": registro.get_value(),
                            "tags": {k: v for k, v in registro.values.items() if not k.startswith('_') and k not in ('result', 'table')},
                        })
            except Exception as e:
                logging.error(f"Erro ao consultar {measurement} para {session_id}: {str(e)}")

        return saida

    def apagar_por_session_id(self, session_id: str, inicio: str = "1970-01-01T00:00:00Z") -> bool:
        """Apaga todos os pontos vinculados a uma sessao (LGPD — exclusao).

        Usa o DELETE API do InfluxDB 2.x. Exige que o token tenha permissao de escrita
        no bucket e que o predicado contenha ao menos um tag match.
        """
        if not self.enabled or not self.client:
            return False

        session_id = _validar_session_id(session_id)
        inicio = _validar_tempo("inicio", inicio)
        agora = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        sucesso = True
        try:
            delete_api = self.client.delete_api()
            for measurement in ("page_analytics", "web_vitals", "custom_events"):
                predicado = f'_measurement="{measurement}" AND session_id="{session_id}"'
                try:
                    delete_api.delete(start=inicio, stop=agora,
                                      predicate=predicado, bucket=self.bucket, org=self.org)
                except Exception as e:
                    logging.error(f"Erro ao apagar {measurement} para {session_id}: {str(e)}")
                    sucesso = False
        except Exception as e:
            logging.error(f"Erro ao iniciar DELETE API: {str(e)}")
            return False
        return sucesso

    # ==================== SAUDE ====================

    def is_healthy(self) -> bool:
        if not self.enabled or not self.client:
            return False
        try:
            health = self.client.health()
            return health.status == "pass"
        except Exception:
            return False

    def fila_pendente(self) -> int:
        """Tamanho da fila do executor (backpressure signal). Retorna 0 quando nao suportado."""
        try:
            return self.executor._work_queue.qsize()  # type: ignore[attr-defined]
        except Exception:
            return 0

    def close(self):
        if self.client:
            self.client.close()
        if self.executor:
            self.executor.shutdown(wait=True)


# Singleton global
_influxdb_service: Optional[InfluxDBService] = None


def get_influxdb_service() -> InfluxDBService:
    global _influxdb_service
    if _influxdb_service is None:
        from config import config
        import os

        config_name = os.environ.get('FLASK_ENV', 'development')
        app_config = config.get(config_name, config['default'])()

        _influxdb_service = InfluxDBService(
            url=app_config.INFLUXDB_URL,
            token=app_config.INFLUXDB_TOKEN,
            org=app_config.INFLUXDB_ORG,
            bucket=app_config.INFLUXDB_BUCKET,
            enabled=app_config.INFLUXDB_ENABLED,
        )
    return _influxdb_service


# ==================== FACTORIES (heatmap_data -> metrics) ====================

def _extrair_pagina(page_data):
    if isinstance(page_data, list) and page_data:
        return page_data[-1]
    if isinstance(page_data, dict):
        return page_data
    return None


def _contar_por_tipo(eventos, tipo: str) -> int:
    return sum(1 for e in eventos or [] if isinstance(e, dict) and e.get('tipo') == tipo)


def create_temporal_metric_from_heatmap(session_id: str, heatmap_data: dict,
                                      user_agent: str = None, ip_address: str = None,
                                      device_type: str = None, pais: str = None,
                                      referrer_dominio: str = None,
                                      user_id: Optional[str] = None,
                                      user_bucket: Optional[str] = None,
                                      group_id: Optional[str] = None,
                                      group_bucket: Optional[str] = None,
                                      site_slug: Optional[str] = None) -> List[TemporalMetric]:
    """Agrega contagens por tipo de evento em metricas temporais (uma por pagina)."""
    metrics: List[TemporalMetric] = []

    paginas = {}
    if isinstance(heatmap_data.get('paginas'), dict):
        paginas.update(heatmap_data['paginas'])

    app_id = heatmap_data.get('app_id') if isinstance(heatmap_data, dict) else None
    ambiente = heatmap_data.get('ambiente') if isinstance(heatmap_data, dict) else None

    for page_type, page_data in paginas.items():
        page_info = _extrair_pagina(page_data)
        if not page_info:
            continue

        eventos = page_info.get('eventos', []) or []

        metrics.append(TemporalMetric(
            session_id=session_id,
            page_type=page_type,
            permanencia_segundos=float(page_info.get('segundos', 0)),
            visualizacoes=int(page_info.get('visualizacoes', 0)),
            cliques=_contar_por_tipo(eventos, 'click'),
            scrolls=_contar_por_tipo(eventos, 'scroll_depth'),
            mouse_moves=_contar_por_tipo(eventos, 'mouse_move'),
            toques=_contar_por_tipo(eventos, 'touch'),
            hovers=_contar_por_tipo(eventos, 'hover'),
            exposicoes=_contar_por_tipo(eventos, 'element_exposure'),
            custom_events=_contar_por_tipo(eventos, 'custom'),
            timestamp=datetime.now(timezone.utc),
            user_agent=user_agent,
            ip_address=ip_address,
            app_id=app_id,
            ambiente=ambiente,
            device_type=device_type,
            pais=pais,
            referrer_dominio=referrer_dominio,
            user_id=user_id,
            user_bucket=user_bucket,
            group_id=group_id,
            group_bucket=group_bucket,
            site_slug=site_slug,
        ))

    return metrics


def create_web_vitals_from_heatmap(session_id: str, heatmap_data: dict,
                                   user_agent: str = None, ip_address: str = None,
                                   device_type: str = None, pais: str = None,
                                   referrer_dominio: str = None,
                                   user_id: Optional[str] = None,
                                   user_bucket: Optional[str] = None,
                                   group_id: Optional[str] = None,
                                   group_bucket: Optional[str] = None,
                                   site_slug: Optional[str] = None) -> List[WebVitalMetric]:
    resultado: List[WebVitalMetric] = []

    paginas = {}
    if isinstance(heatmap_data.get('paginas'), dict):
        paginas.update(heatmap_data['paginas'])

    app_id = heatmap_data.get('app_id') if isinstance(heatmap_data, dict) else None
    ambiente = heatmap_data.get('ambiente') if isinstance(heatmap_data, dict) else None

    for page_type, page_data in paginas.items():
        page_info = _extrair_pagina(page_data)
        if not page_info:
            continue

        for evento in page_info.get('eventos', []) or []:
            if not isinstance(evento, dict) or evento.get('tipo') != 'web_vital':
                continue
            dados = evento.get('dados') or {}
            nome = dados.get('nome')
            valor = dados.get('valor')
            if not nome or valor is None:
                continue

            resultado.append(WebVitalMetric(
                session_id=session_id,
                page_type=page_type,
                nome=str(nome),
                valor=float(valor),
                rating=dados.get('rating'),
                metric_id=dados.get('id'),
                timestamp=datetime.now(timezone.utc),
                user_agent=user_agent,
                ip_address=ip_address,
                app_id=app_id,
                ambiente=ambiente,
                device_type=device_type,
                pais=pais,
                referrer_dominio=referrer_dominio,
                user_id=user_id,
                user_bucket=user_bucket,
                group_id=group_id,
                group_bucket=group_bucket,
                site_slug=site_slug,
            ))

    return resultado


def create_custom_events_from_heatmap(session_id: str, heatmap_data: dict,
                                      user_agent: str = None, ip_address: str = None,
                                      device_type: str = None, pais: str = None,
                                      referrer_dominio: str = None,
                                      user_id: Optional[str] = None,
                                      user_bucket: Optional[str] = None,
                                      group_id: Optional[str] = None,
                                      group_bucket: Optional[str] = None,
                                      site_slug: Optional[str] = None) -> List[CustomEventMetric]:
    resultado: List[CustomEventMetric] = []

    paginas = {}
    if isinstance(heatmap_data.get('paginas'), dict):
        paginas.update(heatmap_data['paginas'])

    app_id = heatmap_data.get('app_id') if isinstance(heatmap_data, dict) else None
    ambiente = heatmap_data.get('ambiente') if isinstance(heatmap_data, dict) else None

    for page_type, page_data in paginas.items():
        page_info = _extrair_pagina(page_data)
        if not page_info:
            continue

        for evento in page_info.get('eventos', []) or []:
            if not isinstance(evento, dict) or evento.get('tipo') != 'custom':
                continue
            dados = evento.get('dados') or {}
            nome = dados.get('nome')
            if not nome:
                continue
            # Eventos SDK internos (identidade + comerciais) nao entram aqui.
            if nome in _EVENTOS_IDENTIDADE or nome in _EVENTOS_CONVERSAO:
                continue
            propriedades = dados.get('propriedades') or {}
            if not isinstance(propriedades, dict):
                propriedades = {}

            resultado.append(CustomEventMetric(
                session_id=session_id,
                page_type=page_type,
                nome=str(nome),
                propriedades=propriedades,
                timestamp=datetime.now(timezone.utc),
                user_agent=user_agent,
                ip_address=ip_address,
                app_id=app_id,
                ambiente=ambiente,
                device_type=device_type,
                pais=pais,
                referrer_dominio=referrer_dominio,
                user_id=user_id,
                user_bucket=user_bucket,
                group_id=group_id,
                group_bucket=group_bucket,
                site_slug=site_slug,
            ))

    return resultado


def create_conversion_events_from_heatmap(session_id: str, heatmap_data: dict,
                                          user_agent: str = None, ip_address: str = None,
                                          device_type: str = None, pais: str = None,
                                          referrer_dominio: str = None,
                                          user_id: str = None, user_bucket: str = None,
                                          group_id: str = None, group_bucket: str = None,
                                          site_slug: Optional[str] = None,
                                          ) -> List[ConversionEventMetric]:
    """Extrai eventos comerciais (__purchase/__signup/__conversion) do heatmap."""
    resultado: List[ConversionEventMetric] = []

    paginas = {}
    if isinstance(heatmap_data.get('paginas'), dict):
        paginas.update(heatmap_data['paginas'])

    app_id = heatmap_data.get('app_id') if isinstance(heatmap_data, dict) else None
    ambiente = heatmap_data.get('ambiente') if isinstance(heatmap_data, dict) else None

    for page_type, page_data in paginas.items():
        page_info = _extrair_pagina(page_data)
        if not page_info:
            continue

        for evento in page_info.get('eventos', []) or []:
            if not isinstance(evento, dict) or evento.get('tipo') != 'custom':
                continue
            dados = evento.get('dados') or {}
            nome = dados.get('nome')
            if nome not in _EVENTOS_CONVERSAO:
                continue
            propriedades = dados.get('propriedades') or {}
            if not isinstance(propriedades, dict):
                propriedades = {}

            if nome == '__purchase':
                tipo = 'purchase'
                raw = propriedades.get('value')
                valor = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
                moeda = str(propriedades['currency']) if propriedades.get('currency') else None
                plano = None
            elif nome == '__signup':
                tipo = 'signup'
                valor = None
                moeda = None
                plano = str(propriedades['plan']) if propriedades.get('plan') else None
            else:  # __conversion
                tipo = str(propriedades.get('type', 'conversion')).strip() or 'conversion'
                raw = propriedades.get('value')
                valor = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
                moeda = None
                plano = None

            campos_extraidos = {'value', 'currency', 'plan', 'type'}
            props_extras = {k: v for k, v in propriedades.items() if k not in campos_extraidos}

            resultado.append(ConversionEventMetric(
                session_id=session_id,
                page_type=page_type,
                nome=str(nome),
                tipo=tipo,
                propriedades=props_extras,
                valor=valor,
                moeda=moeda,
                plano=plano,
                timestamp=datetime.now(timezone.utc),
                user_agent=user_agent,
                ip_address=ip_address,
                app_id=app_id,
                ambiente=ambiente,
                device_type=device_type,
                pais=pais,
                referrer_dominio=referrer_dominio,
                user_id=user_id,
                user_bucket=user_bucket,
                group_id=group_id,
                group_bucket=group_bucket,
                site_slug=site_slug,
            ))

    return resultado
