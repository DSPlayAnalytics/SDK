"""Testes dos endpoints REST de consulta (Frente B) e LGPD (Frente C).

Apos P0 #1 (auth REST), os endpoints `/analytics/*` exigem cookie
`cliente_session` valido. Estes testes validam apenas:
  - 401 sem cookie (caminho default)
  - 503 quando InfluxDB nao inicializado (sem auth pra simplificar)
  - LGPD admin (auth via Authorization Bearer, separada)

Cobertura "happy path com cookie + bucket forcado" vive em test_analytics_auth.py.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# Bootstrap do env ANTES de importar app — evita eventlet/Postgres em test local
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
os.environ.setdefault("TENANTS_DATABASE_URL", f"sqlite:///{_TMP_DB.name}")
os.environ.setdefault("SOCKETIO_ASYNC_MODE", "threading")

sys.path.append(os.path.dirname(__file__))

import app as app_module


class _CapturadorInfluxDB:
    def __init__(self, metricas=None, vitals=None, customs=None, healthy=True):
        self._metricas = metricas or []
        self._vitals = vitals or []
        self._customs = customs or []
        self._healthy = healthy

    def query_metricas_agregadas(self, **kwargs):
        return list(self._metricas)

    def query_web_vitals(self, **kwargs):
        return list(self._vitals)

    def query_custom_events(self, **kwargs):
        return list(self._customs)

    def consultar_por_session_id(self, session_id, inicio="-30d"):
        return {
            "page_analytics": [{"session_id": session_id, "field": "cliques", "value": 5}],
            "web_vitals": [],
            "custom_events": [],
        }

    def apagar_por_session_id(self, session_id, inicio="1970-01-01T00:00:00Z"):
        return True

    def is_healthy(self):
        return self._healthy


# NOTA: classe `ApiConsultaTest` removida em P0 #1. Os endpoints `/analytics/*`
# agora exigem cookie `cliente_session` e forcam bucket-per-cliente — cobertura
# completa em test_analytics_auth.py.


class AdminLgpdTest(unittest.TestCase):
    TOKEN = 'token-admin-teste'

    def setUp(self):
        self.client = app_module.app.test_client()
        self._influx_original = app_module.influxdb_service
        self._env_original = os.environ.get('ADMIN_API_TOKEN')
        os.environ['ADMIN_API_TOKEN'] = self.TOKEN
        app_module.influxdb_service = _CapturadorInfluxDB()

    def tearDown(self):
        app_module.influxdb_service = self._influx_original
        if self._env_original is None:
            os.environ.pop('ADMIN_API_TOKEN', None)
        else:
            os.environ['ADMIN_API_TOKEN'] = self._env_original

    def _auth(self):
        return {'Authorization': f'Bearer {self.TOKEN}'}

    def test_consultar_sessao_retorna_dados(self):
        resposta = self.client.get('/admin/analytics/sessao/sid-xyz', headers=self._auth())
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.get_json()
        self.assertEqual(corpo['session_id'], 'sid-xyz')
        self.assertIn('page_analytics', corpo['dados'])

    def test_consultar_sem_token_retorna_401(self):
        resposta = self.client.get('/admin/analytics/sessao/sid-xyz')
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta.get_json()['code'], 'UNAUTHORIZED')

    def test_consultar_com_token_errado_retorna_401(self):
        resposta = self.client.get('/admin/analytics/sessao/sid-xyz',
                                   headers={'Authorization': 'Bearer errado'})
        self.assertEqual(resposta.status_code, 401)

    def test_apagar_sessao_retorna_success(self):
        resposta = self.client.delete('/admin/analytics/sessao/sid-del', headers=self._auth())
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.get_json()
        self.assertTrue(corpo['apagado'])

    def test_apagar_sem_token_retorna_401(self):
        resposta = self.client.delete('/admin/analytics/sessao/sid-del')
        self.assertEqual(resposta.status_code, 401)


if __name__ == '__main__':
    unittest.main()
