"""Servico de ingestao: recebe payload cru do handler e cuida de validacao,
transformacao em metricas e delegacao ao InfluxDB. Isola o handler Socket.IO
da regra de ingestao, o que permite testar o fluxo sem subir socket real.

Schema de ack: 1.1 (ver docs/plano-garantias-sdk-backend.md, secao 1.4).
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from dto.Dados import HeatmapDados
from influxdb_service import (
    create_conversion_events_from_heatmap,
    create_custom_events_from_heatmap,
    create_temporal_metric_from_heatmap,
    create_web_vitals_from_heatmap,
)
from ingestao.cardinalidade import TrackerCardinalidade, limite_para_plano
from ingestao.derivacoes import (
    derivar_group_bucket,
    derivar_user_bucket,
    detectar_device_type,
    extrair_pais,
    extrair_referrer_dominio,
)
from ingestao.idempotencia import (
    EntradaIdempotencia,
    obter_cache_idempotencia,
    obter_registro_ultimo,
    obter_sequenciador,
)
from ingestao.logs import emitir_log


# Metrics Prometheus: best-effort. Em ambiente de teste sem prometheus_client
# instalado, ou se metrics nao foi inicializado, vira no-op.
def _registrar_metric_evento_recebido(tipo: str) -> None:
    try:
        from metrics import obter_metrics
        obter_metrics().eventos_recebidos(tipo=tipo)
    except Exception:
        pass


def _registrar_metric_evento_rejeitado(code: str) -> None:
    try:
        from metrics import obter_metrics
        obter_metrics().eventos_rejeitados(code=code)
    except Exception:
        pass
from ingestao.rejeicoes_diarias import obter_contador as _obter_contador_rejeicoes
from ingestao.validador import validar_payload


def _incrementar_rejeicao_diaria(site_id, tipo: str) -> None:
    """Best-effort: falha silenciosa para nao derrubar o caminho de ingestao."""
    try:
        _obter_contador_rejeicoes().incrementar(site_id, tipo)
    except Exception:
        pass

logger = logging.getLogger('analytics.ingestao')


SCHEMA_VERSION_ACK = "1.2"

# Limites do plausibility de timestamp (Onda 2 — ja antecipado aqui porque
# os timestamps sao calculados neste caminho e o custo e trivial).
JANELA_PASSADO_MS = 24 * 60 * 60 * 1000       # 24h atras
JANELA_FUTURO_MS = 5 * 60 * 1000              # 5min no futuro
JANELA_MAXIMA_MS = 60 * 60 * 1000             # 1h entre timestamp_inicial e timestamp_final

# Thresholds de backpressure (Onda 3) — antecipados para compor o ack desde ja.
BACKPRESSURE_SLOW_ACIMA = 50
BACKPRESSURE_STOP_ACIMA = 200


@dataclass
class ResumoIngestao:
    """Contrato de ack schema 1.1.

    Campos novos em relacao a 1.0:
      - `server_seq`: monotonico por site, detecta gap no cliente.
      - `server_time_ms`: referencia para correcao de skew no SDK.
      - `retriable`: indica se erro e transitorio (True) ou definitivo (False).
      - `backpressure_hint`: 'ok' | 'slow' | 'stop'.
    """

    status: str
    id_registro: Optional[str] = None
    tipo_envio: Optional[str] = None
    resumo: Optional[Dict[str, Any]] = None
    code: Optional[str] = None
    message: Optional[str] = None
    erros: List[str] = field(default_factory=list)

    server_seq: Optional[int] = None
    server_time_ms: Optional[int] = None
    retriable: Optional[bool] = None
    backpressure_hint: str = "ok"
    duplicado: bool = False

    def to_dict(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION_ACK,
            "id_registro": self.id_registro,
            "server_seq": self.server_seq,
            "server_time": self.server_time_ms,
            "backpressure_hint": self.backpressure_hint,
        }

        if self.status == "success":
            base.update({
                "status": "success",
                "tipo_envio": self.tipo_envio,
                "resumo": self.resumo or {},
                "duplicado": self.duplicado,
            })
            return base

        base.update({
            "status": "error",
            "code": self.code or "INVALID_ANALYTICS_PAYLOAD",
            "message": self.message or "Payload de analytics invalido",
            "fields": self.erros,
            "retriable": self.retriable if self.retriable is not None else False,
        })
        return base


def _now_ms() -> int:
    return int(time.time() * 1000)


def _classificar_backpressure(fila_pendente: int) -> str:
    if fila_pendente > BACKPRESSURE_STOP_ACIMA:
        return "stop"
    if fila_pendente > BACKPRESSURE_SLOW_ACIMA:
        return "slow"
    return "ok"


def _validar_timestamps(data: dict, server_time_ms: int) -> Optional[str]:
    """Retorna mensagem de erro ou None se ok."""
    ti = data.get("timestamp_inicial")
    tf = data.get("timestamp_final")
    if not isinstance(ti, (int, float)) or not isinstance(tf, (int, float)):
        return None  # validador de payload ja trata tipo
    ti = int(ti)
    tf = int(tf)
    if ti < server_time_ms - JANELA_PASSADO_MS:
        return "timestamp_inicial muito antigo"
    if ti > server_time_ms + JANELA_FUTURO_MS:
        return "timestamp_inicial no futuro"
    if tf < ti:
        return "timestamp_final anterior a timestamp_inicial"
    if tf - ti > JANELA_MAXIMA_MS:
        return "janela de timestamps maior que 1h"
    return None


class ServicoIngestao:
    """Encapsula validacao + transformacao + persistencia.

    O handler Socket.IO so precisa chamar `ingerir(...)` e devolver o ack.

    Quando `sites_cache` e fornecido, o servico resolve `site_id -> bucket_name`
    e roteia a escrita para o bucket dedicado do cliente. Sites sem `bucket_name`
    cadastrado caem no bucket default do `influxdb_service` (compat legado).
    """

    def __init__(self, influxdb_service=None, sites_cache=None, tenants_repo=None,
                 cardinalidade_tracker: Optional[TrackerCardinalidade] = None):
        self.influxdb_service = influxdb_service
        self.sites_cache = sites_cache
        # tenants_repo: usado para enforcement de quota (sec 18 do dashboard-cliente.md).
        # Quando ausente, ingest aceita qualquer volume (modo dev/legado).
        self.tenants_repo = tenants_repo
        # cardinalidade_tracker: enforcement por plano (sec 20). Sem tracker
        # nao ha enforcement — preserva compat com testes que nao se importam.
        self.cardinalidade_tracker = cardinalidade_tracker
        self._cache = obter_cache_idempotencia()
        self._ultimos = obter_registro_ultimo()
        self._sequenciador = obter_sequenciador()

    def ingerir(
        self,
        session_id: str,
        data: dict,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        site_id: Optional[str] = None,
        referer: Optional[str] = None,
        cf_ipcountry: Optional[str] = None,
    ) -> ResumoIngestao:
        id_registro = data.get('id_registro') if isinstance(data, dict) else None
        app_id = data.get('app_id') if isinstance(data, dict) else None
        analytics_session_id = data.get('session_id') if isinstance(data, dict) else None
        # Derivacoes server-side (sec 20). Calculadas 1x e propagadas.
        device_type = detectar_device_type(user_agent)
        pais = extrair_pais(cf_ipcountry)
        referrer_dominio = extrair_referrer_dominio(referer)

        emitir_log(logger, logging.INFO, 'recebido',
                   session_id=session_id, id_registro=id_registro, app_id=app_id,
                   site_id=site_id)

        fila_pendente = 0
        if self.influxdb_service:
            try:
                valor = self.influxdb_service.fila_pendente()
                # Guarda defensiva: mocks de teste retornam MagicMock; aceita so int.
                if isinstance(valor, int):
                    fila_pendente = valor
                    if fila_pendente > BACKPRESSURE_SLOW_ACIMA:
                        emitir_log(logger, logging.WARNING, 'backpressure',
                                   session_id=session_id, id_registro=id_registro,
                                   fila_pendente=fila_pendente)
            except Exception:
                fila_pendente = 0
        backpressure = _classificar_backpressure(fila_pendente)

        # ---------- idempotencia (Onda 1) ----------
        if id_registro:
            hit = self._cache.ver(site_id, id_registro)
            if hit is not None:
                emitir_log(logger, logging.INFO, 'duplicado',
                           session_id=session_id, id_registro=id_registro, site_id=site_id)
                resumo_hit = dict(hit.resumo_dict)
                resumo_hit["duplicado"] = True
                resumo_hit["backpressure_hint"] = backpressure
                return _dict_para_resumo(resumo_hit)

        # ---------- validacao estrutural ----------
        valido, erros = validar_payload(data)
        if not valido:
            emitir_log(logger, logging.WARNING, 'rejeitado',
                       session_id=session_id, id_registro=id_registro, app_id=app_id,
                       erros=';'.join(erros))
            return ResumoIngestao(
                status='error',
                id_registro=id_registro,
                code='INVALID_ANALYTICS_PAYLOAD',
                message='Payload de analytics invalido',
                erros=erros,
                retriable=False,
                server_seq=self._sequenciador.proximo(site_id),
                server_time_ms=_now_ms(),
                backpressure_hint=backpressure,
            )

        # ---------- validacao de timestamps (Onda 2) ----------
        server_time = _now_ms()
        erro_ts = _validar_timestamps(data, server_time)
        if erro_ts:
            emitir_log(logger, logging.WARNING, 'rejeitado_timestamp',
                       session_id=session_id, id_registro=id_registro, motivo=erro_ts)
            return ResumoIngestao(
                status='error',
                id_registro=id_registro,
                code='INVALID_TIMESTAMP',
                message=erro_ts,
                erros=['timestamp_inicial', 'timestamp_final'],
                retriable=False,
                server_seq=self._sequenciador.proximo(site_id),
                server_time_ms=server_time,
                backpressure_hint=backpressure,
            )

        heatmap_dados = HeatmapDados.from_dict(data)
        emitir_log(logger, logging.INFO, 'validado',
                   session_id=session_id, id_registro=heatmap_dados.id_registro,
                   app_id=app_id, site_id=site_id)

        # ---------- quota diaria (sec 18 do dashboard-cliente.md) ----------
        if self._quota_excedida(site_id):
            emitir_log(logger, logging.WARNING, 'rejeitado_quota_excedida',
                       session_id=session_id, id_registro=id_registro, site_id=site_id)
            _registrar_metric_evento_rejeitado("QUOTA_EXCEDIDA")
            _incrementar_rejeicao_diaria(site_id, "QUOTA_EXCEDIDA")
            return ResumoIngestao(
                status='error',
                id_registro=id_registro,
                code='QUOTA_EXCEDIDA',
                message='Cota diaria do plano atingida; aguarde reset 00:00 UTC',
                erros=['site_id'],
                # retriable=False: SDK descarta silenciosamente. Quota reabre em
                # 24h, retry exponencial nao ajuda — so gera ruido em log.
                retriable=False,
                server_seq=self._sequenciador.proximo(site_id),
                server_time_ms=server_time,
                backpressure_hint=backpressure,
            )

        bucket_destino, site_slug, motivo_bucket = self._resolver_bucket(
            site_id, session_id, id_registro,
        )
        if motivo_bucket == 'site_sem_bucket':
            # Strict routing: site identificado mas sem bucket dedicado seria um
            # leak entre tenants (cairia no INFLUXDB_BUCKET default). Rejeita ao
            # inves de fallback. site_id=None continua passando para preservar
            # compat dev (SDK_AUTH_REQUIRED=false) — a fonte do leak fica unica.
            emitir_log(logger, logging.WARNING, 'rejeitado_bucket_nao_provisionado',
                       session_id=session_id, id_registro=id_registro, site_id=site_id)
            return ResumoIngestao(
                status='error',
                id_registro=id_registro,
                code='BUCKET_NAO_PROVISIONADO',
                message='Site nao tem bucket dedicado; rode provisionar_cliente.py',
                erros=['site_id'],
                retriable=False,
                server_seq=self._sequenciador.proximo(site_id),
                server_time_ms=server_time,
                backpressure_hint=backpressure,
            )

        # ---------- cardinalidade (sec 20 do dashboard-cliente.md) ----------
        cardinalidade_resultado = self._verificar_cardinalidade(
            site_id, data, analytics_session_id, session_id, id_registro,
            device_type=device_type, pais=pais, referrer_dominio=referrer_dominio,
        )
        if cardinalidade_resultado is not None:
            # `cardinalidade_resultado` carrega o ack pronto.
            cardinalidade_resultado.server_seq = self._sequenciador.proximo(site_id)
            cardinalidade_resultado.server_time_ms = server_time
            cardinalidade_resultado.backpressure_hint = backpressure
            return cardinalidade_resultado

        # Schema 1.2 (SDK v0.4): identidade opcional. Computa buckets server-side
        # — cliente nao confia em bucket pre-calculado (poderia falsificar
        # retention buckets pra inflar metricas de outro user).
        user_id = data.get('user_id') if isinstance(data, dict) else None
        group_id = data.get('group_id') if isinstance(data, dict) else None
        user_bucket = derivar_user_bucket(user_id)
        group_bucket = derivar_group_bucket(group_id)

        self._persistir_com_resiliencia(
            session_id, data, user_agent, ip_address,
            app_id=app_id, bucket=bucket_destino,
            device_type=device_type, pais=pais, referrer_dominio=referrer_dominio,
            user_id=user_id, user_bucket=user_bucket,
            group_id=group_id, group_bucket=group_bucket,
            site_slug=site_slug,
        )

        resumo = ResumoIngestao(
            status='success',
            id_registro=heatmap_dados.id_registro,
            tipo_envio='temporal',
            server_seq=self._sequenciador.proximo(site_id),
            server_time_ms=server_time,
            backpressure_hint=backpressure,
            resumo={
                'total_visualizacoes': heatmap_dados.get_total_visualizacoes(),
                'total_cliques': heatmap_dados.get_total_cliques(),
                'tempo_total_segundos': heatmap_dados.get_total_tempo_segundos(),
                'duracao_sessao_segundos': heatmap_dados.get_duracao_sessao_segundos(),
                'paginas_visitadas': {
                    page_id: len(paginas)
                    for page_id, paginas in heatmap_dados.paginas.items()
                },
            },
        )

        # Registra ack em cache de idempotencia e rastreio de ultimo recebido.
        if id_registro:
            self._cache.gravar(site_id, id_registro, EntradaIdempotencia(
                resumo_dict=resumo.to_dict(),
                server_seq=resumo.server_seq or 0,
                server_time_ms=resumo.server_time_ms or server_time,
            ))
        if analytics_session_id and id_registro:
            self._ultimos.registrar(analytics_session_id, id_registro, ts_ms=server_time)

        # Quota diaria — incrementa apos persistir (best-effort; falha so loga).
        self._registrar_consumo(site_id)

        return resumo

    def _extrair_pares_tags(self, data: dict, analytics_session_id: Optional[str],
                            device_type: Optional[str] = None,
                            pais: Optional[str] = None,
                            referrer_dominio: Optional[str] = None,
                            ) -> list[tuple[str, str]]:
        """Lista pares (tag, valor) que serao escritos como tag em algum measurement.

        Reflete o conjunto de `.tag(...)` em InfluxDBService.write_*. Mantem
        sincronizado: se um campo deixa de ser tag (ex: ip_address virou field),
        sai daqui tambem. Tags escolhidas: app_id, ambiente, page_type,
        session_id (page_analytics), nome (custom_events/web_vitals), rating
        (web_vitals), device_type, pais, referrer_dominio (sprint 2 bloco B).
        """
        pares: list[tuple[str, str]] = []
        if not isinstance(data, dict):
            return pares
        if data.get('app_id'):
            pares.append(('app_id', data['app_id']))
        if data.get('ambiente'):
            pares.append(('ambiente', data['ambiente']))
        if analytics_session_id:
            pares.append(('session_id', analytics_session_id))
        if device_type:
            pares.append(('device_type', device_type))
        if pais:
            pares.append(('pais', pais))
        if referrer_dominio:
            pares.append(('referrer_dominio', referrer_dominio))
        paginas = data.get('paginas') or {}
        if isinstance(paginas, dict):
            for page_type, lista in paginas.items():
                pares.append(('page_type', page_type))
                if not isinstance(lista, list):
                    continue
                for pagina in lista:
                    if not isinstance(pagina, dict):
                        continue
                    for evento in pagina.get('eventos') or []:
                        if not isinstance(evento, dict):
                            continue
                        tipo = evento.get('tipo')
                        dados = evento.get('dados') or {}
                        nome = dados.get('nome')
                        if tipo == 'custom' and nome:
                            pares.append(('nome', nome))
                        elif tipo == 'web_vital':
                            if nome:
                                pares.append(('nome', nome))
                            rating = dados.get('rating')
                            if rating:
                                pares.append(('rating', rating))
        return pares

    def _verificar_cardinalidade(
        self,
        site_id: Optional[str],
        data: dict,
        analytics_session_id: Optional[str],
        session_id: str,
        id_registro: Optional[str],
        device_type: Optional[str] = None,
        pais: Optional[str] = None,
        referrer_dominio: Optional[str] = None,
    ) -> Optional[ResumoIngestao]:
        """Roda o tracker. Retorna `None` quando aceito ou tracker ausente.

        Quando rejeita, retorna ResumoIngestao parcialmente preenchido — o
        chamador completa `server_seq`, `server_time_ms`, `backpressure_hint`.
        """
        if not self.cardinalidade_tracker or not site_id:
            return None
        plano = None
        if self.sites_cache:
            site = self.sites_cache.obter_site(site_id)
            plano = site.plano if site else None
        limite = limite_para_plano(plano)
        pares = self._extrair_pares_tags(
            data, analytics_session_id,
            device_type=device_type, pais=pais, referrer_dominio=referrer_dominio,
        )
        ok, tag_dominante, total = self.cardinalidade_tracker.verificar_e_registrar(
            site_id, pares, limite,
        )
        if ok:
            # Aceitou: checa se cruzou threshold de alerta (80/95). Cada nivel
            # emite UMA UNICA VEZ por restart (estado interno do tracker).
            nivel = self.cardinalidade_tracker.alerta_pendente(site_id, limite)
            if nivel is not None:
                emitir_log(logger, logging.WARNING, 'cardinalidade_alerta',
                           site_id=site_id, plano=plano, limite=limite,
                           nivel_pct=nivel, total=total)
            return None
        emitir_log(logger, logging.WARNING, 'rejeitado_cardinalidade_excedida',
                   session_id=session_id, id_registro=id_registro,
                   site_id=site_id, plano=plano, limite=limite,
                   total=total, tag_dominante=tag_dominante)
        _registrar_metric_evento_rejeitado("CARDINALIDADE_EXCEDIDA")
        _incrementar_rejeicao_diaria(site_id, "CARDINALIDADE_EXCEDIDA")
        return ResumoIngestao(
            status='error',
            id_registro=id_registro,
            code='CARDINALIDADE_EXCEDIDA',
            message=(f'Cardinalidade do plano {plano or "free"} ({limite} valores) '
                     f'atingida; tag dominante: {tag_dominante}'),
            erros=[tag_dominante or 'tags'],
            retriable=False,
        )

    def _quota_excedida(self, site_id: Optional[str]) -> bool:
        """Verifica `consumo_diario.eventos >= quotas.eventos_por_dia`.

        Retorna False quando nao ha repo (modo legado), site_id ausente, ou
        falha ao consultar (degrada permitindo — preferimos perder enforcement
        do que derrubar ingest).
        """
        if not self.tenants_repo or not site_id:
            return False
        try:
            quota = self.tenants_repo.obter_quota(site_id)
            if quota is None:
                return False
            consumido = self.tenants_repo.consumo_hoje(site_id)
            return consumido >= quota.eventos_por_dia
        except Exception as erro:
            emitir_log(logger, logging.ERROR, 'quota_check_erro',
                       site_id=site_id, motivo=str(erro))
            return False

    def _registrar_consumo(self, site_id: Optional[str]) -> None:
        if not self.tenants_repo or not site_id:
            return
        try:
            self.tenants_repo.incrementar_consumo(site_id, eventos=1)
        except Exception as erro:
            emitir_log(logger, logging.ERROR, 'consumo_increment_erro',
                       site_id=site_id, motivo=str(erro))

    def _resolver_bucket(self, site_id: Optional[str], session_id: str,
                         id_registro: Optional[str]
                         ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Retorna (bucket_name, site_slug, motivo).

        - (bucket, slug, None)        : site provisionado, escreve no bucket dele.
        - (None, None, None)          : site_id=None ou sem cache (legacy/dev) — bucket default.
        - (None, None, 'site_sem_bucket')  : site identificado mas SEM bucket; chamador
                                             deve rejeitar (leak prevention).
        - (None, None, 'sites_cache_erro') : repo ou cache falhou; chamador escolhe se
                                             degrada (escolhi: degrada para default).

        site_slug e o trust-anchor de tenant (= site.slug do Postgres). Server-side,
        nao confiavel via SDK. Propagado pra Influx como tag `site_slug` em
        `_aplicar_identidade`, e usado por filtros multi-tenant em dashboards
        Grafana via `r.site_slug == "${__user.login}"`.
        """
        if not site_id:
            return None, None, None
        if not self.sites_cache:
            return None, None, None
        try:
            site = self.sites_cache.obter_site(site_id)
        except Exception as erro:
            emitir_log(logger, logging.ERROR, 'sites_cache_erro',
                       session_id=session_id, id_registro=id_registro,
                       site_id=site_id, motivo=str(erro))
            return None, None, 'sites_cache_erro'
        bucket = site.bucket_name if site else None
        if not bucket:
            emitir_log(logger, logging.WARNING, 'site_sem_bucket',
                       session_id=session_id, id_registro=id_registro, site_id=site_id)
            return None, None, 'site_sem_bucket'
        return bucket, site.slug, None

    def _persistir_com_resiliencia(
        self,
        session_id: str,
        data: dict,
        user_agent: Optional[str],
        ip_address: Optional[str],
        app_id: Optional[str] = None,
        bucket: Optional[str] = None,
        device_type: Optional[str] = None,
        pais: Optional[str] = None,
        referrer_dominio: Optional[str] = None,
        user_id: Optional[str] = None,
        user_bucket: Optional[str] = None,
        group_id: Optional[str] = None,
        group_bucket: Optional[str] = None,
        site_slug: Optional[str] = None,
    ) -> None:
        """Persistencia em InfluxDB nao deve derrubar a ingestao.

        Erros de InfluxDB sao logados e engolidos. O payload ja foi aceito e validado;
        a ausencia de persistencia e tratada como degradacao, nao como falha do cliente.
        Quando `bucket` e fornecido, escreve no bucket dedicado do cliente; caso contrario
        usa o bucket default do `influxdb_service`.
        """
        if not self.influxdb_service:
            return

        id_registro = data.get('id_registro')

        # Compat: o capturador de testes pode nao aceitar kwarg `bucket`.
        # So passamos quando ha override explicito; assim mocks antigos seguem funcionando.
        kw = {"bucket": bucket} if bucket else {}

        derivadas = {
            "device_type": device_type,
            "pais": pais,
            "referrer_dominio": referrer_dominio,
            "user_id": user_id,
            "user_bucket": user_bucket,
            "group_id": group_id,
            "group_bucket": group_bucket,
            "site_slug": site_slug,
        }
        try:
            metricas = create_temporal_metric_from_heatmap(
                session_id=session_id,
                heatmap_data=data,
                user_agent=user_agent,
                ip_address=ip_address,
                **derivadas,
            )
            for metrica in metricas:
                self.influxdb_service.write_temporal_metrics_async(metrica, **kw)
                _registrar_metric_evento_recebido("page_analytics")
                emitir_log(logger, logging.INFO, 'persistido_temporal',
                           session_id=session_id, id_registro=id_registro, app_id=app_id,
                           page_type=metrica.page_type, bucket=bucket)

            vitals = create_web_vitals_from_heatmap(
                session_id=session_id,
                heatmap_data=data,
                user_agent=user_agent,
                ip_address=ip_address,
                **derivadas,
            )
            for vital in vitals:
                self.influxdb_service.write_web_vital_async(vital, **kw)
                _registrar_metric_evento_recebido("web_vital")
                emitir_log(logger, logging.INFO, 'persistido_webvital',
                           session_id=session_id, id_registro=id_registro, app_id=app_id,
                           nome=vital.nome, valor=vital.valor, bucket=bucket)

            customizados = create_custom_events_from_heatmap(
                session_id=session_id,
                heatmap_data=data,
                user_agent=user_agent,
                ip_address=ip_address,
                **derivadas,
            )
            for custom in customizados:
                self.influxdb_service.write_custom_event_async(custom, **kw)
                _registrar_metric_evento_recebido("custom_event")
                emitir_log(logger, logging.INFO, 'persistido_customevent',
                           session_id=session_id, id_registro=id_registro, app_id=app_id,
                           nome=custom.nome, bucket=bucket)

            conversoes = create_conversion_events_from_heatmap(
                session_id=session_id,
                heatmap_data=data,
                user_agent=user_agent,
                ip_address=ip_address,
                **derivadas,
            )
            for conv in conversoes:
                self.influxdb_service.write_conversion_event_async(conv, **kw)
                _registrar_metric_evento_recebido("conversion_event")
                emitir_log(logger, logging.INFO, 'persistido_conversion',
                           session_id=session_id, id_registro=id_registro, app_id=app_id,
                           nome=conv.nome, tipo=conv.tipo, bucket=bucket)
        except Exception as erro:
            emitir_log(logger, logging.ERROR, 'erro_persistencia',
                       session_id=session_id, id_registro=id_registro, app_id=app_id,
                       motivo=str(erro))


def _dict_para_resumo(d: dict) -> ResumoIngestao:
    """Reconstrucao do dataclass a partir do dict serializado (para hit de cache)."""
    return ResumoIngestao(
        status=d.get("status", "success"),
        id_registro=d.get("id_registro"),
        tipo_envio=d.get("tipo_envio"),
        resumo=d.get("resumo"),
        code=d.get("code"),
        message=d.get("message"),
        erros=d.get("fields") or [],
        server_seq=d.get("server_seq"),
        server_time_ms=d.get("server_time"),
        retriable=d.get("retriable"),
        backpressure_hint=d.get("backpressure_hint", "ok"),
        duplicado=d.get("duplicado", True),
    )
