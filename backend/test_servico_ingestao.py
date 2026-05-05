import os
import sys
import time
import unittest
import uuid

sys.path.append(os.path.dirname(__file__))

from ingestao.idempotencia import resetar_tudo as resetar_idempotencia
from ingestao.servico_ingestao import ServicoIngestao, ResumoIngestao


class InfluxDBCapturador:
    def __init__(self, lancar_erro=False):
        self.metricas = []
        self.web_vitals = []
        self.custom_events = []
        self.conversion_events = []
        self.lancar_erro = lancar_erro

    def write_temporal_metrics_async(self, metrica):
        if self.lancar_erro:
            raise RuntimeError('simulando falha InfluxDB')
        self.metricas.append(metrica)

    def write_web_vital_async(self, metrica):
        self.web_vitals.append(metrica)

    def write_custom_event_async(self, metrica):
        self.custom_events.append(metrica)

    def write_conversion_event_async(self, metrica):
        self.conversion_events.append(metrica)


def payload_valido(id_registro: str | None = None):
    """Gera payload com timestamps dentro da janela de plausibilidade e id unico por padrao."""
    agora_ms = int(time.time() * 1000)
    return {
        "id_registro": id_registro or f"sessao-{uuid.uuid4()}",
        "app_id": "teste-app",
        "ambiente": "production",
        "timestamp_inicial": agora_ms - 5000,
        "timestamp_final": agora_ms,
        "paginas": {
            "/": [
                {
                    "eventos": [
                        {"tipo": "page_view", "timestamp": agora_ms - 4500,
                         "dados": {"page_id": "/", "path": "/"}},
                        {"tipo": "click", "timestamp": agora_ms - 4000,
                         "dados": {"x": 1, "y": 2, "elemento_id": "btn"}},
                        {"tipo": "web_vital", "timestamp": agora_ms - 3000,
                         "dados": {"nome": "LCP", "valor": 1800, "rating": "good"}},
                    ],
                    "visualizacoes": 1,
                    "segundos": 5,
                    "timestamp_inicial": agora_ms - 5000,
                    "timestamp_final": agora_ms,
                }
            ]
        },
    }


class ServicoIngestaoFluxoFelizTest(unittest.TestCase):
    def setUp(self):
        resetar_idempotencia()

    def test_ingestao_feliz_retorna_resumo_success(self):
        capturador = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=capturador)

        payload = payload_valido("sessao-abc-1")
        resumo = servico.ingerir(
            session_id='sessao-socket-1',
            data=payload,
            user_agent='ua-teste',
            ip_address='127.0.0.1',
        )

        self.assertIsInstance(resumo, ResumoIngestao)
        self.assertEqual(resumo.status, 'success')
        self.assertEqual(resumo.id_registro, 'sessao-abc-1')
        self.assertEqual(resumo.tipo_envio, 'temporal')
        self.assertEqual(resumo.resumo['total_visualizacoes'], 1)
        self.assertEqual(resumo.resumo['total_cliques'], 1)
        self.assertEqual(resumo.resumo['paginas_visitadas'], {'/': 1})
        # Schema 1.1: ack carrega server_seq, server_time_ms e backpressure_hint
        self.assertIsNotNone(resumo.server_seq)
        self.assertIsNotNone(resumo.server_time_ms)
        self.assertEqual(resumo.backpressure_hint, 'ok')

    def test_ingestao_feliz_grava_metrica_temporal_e_web_vital(self):
        capturador = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=capturador)

        servico.ingerir(session_id='s1', data=payload_valido())

        self.assertEqual(len(capturador.metricas), 1)
        self.assertEqual(capturador.metricas[0].cliques, 1)

        self.assertEqual(len(capturador.web_vitals), 1)
        self.assertEqual(capturador.web_vitals[0].nome, 'LCP')

    def test_resumo_to_dict_schema_1_2_sucesso(self):
        # Bump 1.1 -> 1.2 acompanha SDK v0.4 (aceita user_id/group_id no envelope).
        # Backend continua aceitando SDK 1.1 — bump nao quebra clientes antigos.
        resumo = ResumoIngestao(
            status='success',
            id_registro='r1',
            tipo_envio='temporal',
            resumo={'total_visualizacoes': 2},
            server_seq=42,
            server_time_ms=1714750000000,
            backpressure_hint='ok',
        )
        self.assertEqual(resumo.to_dict(), {
            'schema_version': '1.2',
            'status': 'success',
            'id_registro': 'r1',
            'tipo_envio': 'temporal',
            'resumo': {'total_visualizacoes': 2},
            'server_seq': 42,
            'server_time': 1714750000000,
            'backpressure_hint': 'ok',
            'duplicado': False,
        })

    def test_idempotencia_mesma_id_registro(self):
        """Enviar o mesmo id_registro 2x grava 1 vez; segundo ack tem duplicado=True."""
        capturador = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=capturador)
        payload = payload_valido("sessao-dup")

        r1 = servico.ingerir(session_id='s1', data=payload, site_id='site-A')
        r2 = servico.ingerir(session_id='s1', data=payload, site_id='site-A')

        self.assertEqual(r1.status, 'success')
        self.assertEqual(r2.status, 'success')
        self.assertFalse(r1.duplicado)
        self.assertTrue(r2.duplicado)
        # So uma gravacao no influxdb
        self.assertEqual(len(capturador.metricas), 1)
        # server_seq do hit deve ser o mesmo do primeiro
        self.assertEqual(r1.server_seq, r2.server_seq)


class ServicoIngestaoFluxoInvalidoTest(unittest.TestCase):
    def setUp(self):
        resetar_idempotencia()

    def test_payload_invalido_retorna_erro_sem_gravar(self):
        capturador = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=capturador)

        resumo = servico.ingerir(session_id='s1', data={'id_registro': '', 'paginas': 'errado'})

        self.assertEqual(resumo.status, 'error')
        self.assertEqual(resumo.code, 'INVALID_ANALYTICS_PAYLOAD')
        self.assertIn('id_registro', resumo.erros)
        self.assertIn('paginas', resumo.erros)
        self.assertEqual(capturador.metricas, [])
        self.assertEqual(capturador.web_vitals, [])
        self.assertFalse(resumo.retriable)

    def test_timestamp_muito_antigo_rejeita(self):
        servico = ServicoIngestao(influxdb_service=InfluxDBCapturador())
        payload = payload_valido("sessao-old")
        payload['timestamp_inicial'] = int(time.time() * 1000) - 48 * 60 * 60 * 1000
        resumo = servico.ingerir(session_id='s1', data=payload)
        self.assertEqual(resumo.status, 'error')
        self.assertEqual(resumo.code, 'INVALID_TIMESTAMP')

    def test_resumo_to_dict_schema_1_2_erro(self):
        resumo = ResumoIngestao(
            status='error',
            code='INVALID_ANALYTICS_PAYLOAD',
            message='x',
            erros=['id_registro', 'paginas'],
            retriable=False,
            server_seq=1,
            server_time_ms=1714750000000,
        )
        payload = resumo.to_dict()
        self.assertEqual(payload['schema_version'], '1.2')
        self.assertEqual(payload['status'], 'error')
        self.assertEqual(payload['code'], 'INVALID_ANALYTICS_PAYLOAD')
        self.assertEqual(payload['fields'], ['id_registro', 'paginas'])
        self.assertEqual(payload['retriable'], False)


class ServicoIngestaoResilienciaTest(unittest.TestCase):
    def setUp(self):
        resetar_idempotencia()

    def test_erro_de_influxdb_nao_derruba_ingestao(self):
        capturador = InfluxDBCapturador(lancar_erro=True)
        servico = ServicoIngestao(influxdb_service=capturador)

        resumo = servico.ingerir(session_id='s1', data=payload_valido())

        # ingestao ainda responde com success — persistencia e resiliente
        self.assertEqual(resumo.status, 'success')

    def test_sem_influxdb_funciona(self):
        servico = ServicoIngestao(influxdb_service=None)
        resumo = servico.ingerir(session_id='s1', data=payload_valido())
        self.assertEqual(resumo.status, 'success')


class ServicoIngestaoUserIdGroupIdTest(unittest.TestCase):
    """Schema 1.2 (SDK v0.4): user_id / group_id no envelope viajam ate o
    InfluxDB como user_bucket (tag, 256 bins via sha256) + user_id (field)
    e simetricamente para group. Decisao D1 opcao C — ver memoria
    project_api_prefix_redundancia / roadmap SDK v0.4.

    Tests asseguram que cada Metric capturado expoe os 4 campos:
      - user_bucket (Optional[str], 'b000'..'b255' ou None)
      - user_id (Optional[str], string opaca exata do envelope)
      - group_bucket (idem)
      - group_id (idem)
    """

    def setUp(self):
        resetar_idempotencia()

    def test_payload_com_user_id_propaga_pra_metric_temporal(self):
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)
        payload = payload_valido()
        payload['user_id'] = 'u-42'

        servico.ingerir(session_id='s1', data=payload)

        self.assertEqual(len(cap.metricas), 1)
        m = cap.metricas[0]
        self.assertEqual(m.user_id, 'u-42')
        self.assertIsNotNone(m.user_bucket)
        self.assertRegex(m.user_bucket, r'^b\d{3}$')

    def test_payload_com_group_id_propaga_independente(self):
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)
        payload = payload_valido()
        payload['group_id'] = 'acme-corp'

        servico.ingerir(session_id='s1', data=payload)

        m = cap.metricas[0]
        self.assertEqual(m.group_id, 'acme-corp')
        self.assertIsNotNone(m.group_bucket)
        self.assertRegex(m.group_bucket, r'^b\d{3}$')
        # Sem user_id no payload, fields ficam None (nao escrevem nada no Point).
        self.assertIsNone(m.user_id)
        self.assertIsNone(m.user_bucket)

    def test_payload_sem_identidade_metric_tem_none(self):
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)

        servico.ingerir(session_id='s1', data=payload_valido())

        m = cap.metricas[0]
        self.assertIsNone(m.user_id)
        self.assertIsNone(m.user_bucket)
        self.assertIsNone(m.group_id)
        self.assertIsNone(m.group_bucket)

    def test_user_id_propaga_pra_web_vital(self):
        # web_vital esta no fixture payload_valido (LCP). Tem que carregar
        # user_id/group_id pra retention de performance por user funcionar.
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)
        payload = payload_valido()
        payload['user_id'] = 'u-perf'

        servico.ingerir(session_id='s1', data=payload)

        self.assertEqual(len(cap.web_vitals), 1)
        wv = cap.web_vitals[0]
        self.assertEqual(wv.user_id, 'u-perf')
        self.assertIsNotNone(wv.user_bucket)

    def test_user_id_propaga_pra_custom_event(self):
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)
        payload = payload_valido()
        # Adiciona um custom event ao fixture pra exercitar a rota.
        agora_ms = payload['timestamp_final']
        payload['paginas']['/'][0]['eventos'].append({
            'tipo': 'custom',
            'timestamp': agora_ms - 1000,
            'dados': {'nome': 'botao_clicado', 'propriedades': {}},
        })
        payload['user_id'] = 'u-custom'

        servico.ingerir(session_id='s1', data=payload)

        self.assertEqual(len(cap.custom_events), 1)
        ce = cap.custom_events[0]
        self.assertEqual(ce.user_id, 'u-custom')
        self.assertIsNotNone(ce.user_bucket)

    def test_user_bucket_deterministico_entre_chamadas(self):
        # Mesmo user_id em ingestoes diferentes gera mesmo bucket — pre-condicao
        # core pra retention queries acharem todos os pontos do user.
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)
        for i in range(3):
            payload = payload_valido(f'reg-{i}')
            payload['user_id'] = 'u-deterministico'
            servico.ingerir(session_id='s1', data=payload)

        buckets = {m.user_bucket for m in cap.metricas}
        self.assertEqual(len(buckets), 1)

    def test_user_id_e_group_id_tem_namespaces_separados(self):
        # user_id 'X' e group_id 'X' nao devem cair no mesmo bucket — isso
        # confundiria correlacao na pivotacao por org.
        from ingestao.derivacoes import derivar_user_bucket, derivar_group_bucket
        a = derivar_user_bucket('mesma-string')
        b = derivar_group_bucket('mesma-string')
        # Pode coincidir por colisao de hash, mas com namespaces diferentes
        # a probabilidade e ~1/256. Pegamos um caso conhecido.
        # 'X' fica em buckets diferentes — namespace user: vs group:.
        # Se este teste flakar por colisao real, trocar a string fixa.
        self.assertNotEqual(a, b,
            f"namespaces deveriam separar — colisao acidental? user={a} group={b}")


class ServicoIngestaoConversionEventsTest(unittest.TestCase):
    """Eventos __purchase/__signup/__conversion vao pra conversion_events,
    nao pra custom_events. Eventos __identify/__group/__reset sao descartados."""

    def setUp(self):
        resetar_idempotencia()

    def _payload_com_eventos(self, *eventos):
        agora_ms = int(time.time() * 1000)
        return {
            "id_registro": f"reg-{uuid.uuid4()}",
            "app_id": "teste-app",
            "ambiente": "production",
            "timestamp_inicial": agora_ms - 5000,
            "timestamp_final": agora_ms,
            "paginas": {
                "/": [{
                    "eventos": list(eventos),
                    "visualizacoes": 1,
                    "segundos": 5,
                    "timestamp_inicial": agora_ms - 5000,
                    "timestamp_final": agora_ms,
                }]
            },
        }

    def test_purchase_vai_pra_conversion_events_nao_custom(self):
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)
        payload = self._payload_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {
                "nome": "__purchase",
                "propriedades": {"value": 99.9, "currency": "BRL"},
            }},
        )
        servico.ingerir(session_id='s1', data=payload)
        self.assertEqual(len(cap.conversion_events), 1)
        self.assertEqual(len(cap.custom_events), 0)
        self.assertEqual(cap.conversion_events[0].tipo, "purchase")
        self.assertAlmostEqual(cap.conversion_events[0].valor, 99.9)
        self.assertEqual(cap.conversion_events[0].moeda, "BRL")

    def test_signup_vai_pra_conversion_events(self):
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)
        payload = self._payload_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {
                "nome": "__signup",
                "propriedades": {"plan": "pro"},
            }},
        )
        servico.ingerir(session_id='s1', data=payload)
        self.assertEqual(len(cap.conversion_events), 1)
        self.assertEqual(cap.conversion_events[0].tipo, "signup")
        self.assertEqual(cap.conversion_events[0].plano, "pro")

    def test_identidade_nao_vai_pra_nenhum_pipeline(self):
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)
        payload = self._payload_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {"nome": "__identify", "propriedades": {}}},
            {"tipo": "custom", "timestamp": 2, "dados": {"nome": "__group", "propriedades": {}}},
            {"tipo": "custom", "timestamp": 3, "dados": {"nome": "__reset", "propriedades": {}}},
        )
        servico.ingerir(session_id='s1', data=payload)
        self.assertEqual(len(cap.custom_events), 0)
        self.assertEqual(len(cap.conversion_events), 0)

    def test_evento_normal_e_purchase_no_mesmo_payload(self):
        cap = InfluxDBCapturador()
        servico = ServicoIngestao(influxdb_service=cap)
        payload = self._payload_com_eventos(
            {"tipo": "custom", "timestamp": 1, "dados": {
                "nome": "__purchase",
                "propriedades": {"value": 10, "currency": "USD"},
            }},
            {"tipo": "custom", "timestamp": 2, "dados": {
                "nome": "botao_clicado",
                "propriedades": {"id": "checkout"},
            }},
        )
        servico.ingerir(session_id='s1', data=payload)
        self.assertEqual(len(cap.conversion_events), 1)
        self.assertEqual(len(cap.custom_events), 1)
        self.assertEqual(cap.custom_events[0].nome, "botao_clicado")


if __name__ == '__main__':
    unittest.main()
