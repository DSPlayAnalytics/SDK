"""TDD do blueprint /cliente/exportar.

Endpoints:
  GET /cliente/exportar           — lista os arquivos disponiveis do slug do user (JSON)
  GET /cliente/exportar/<dia>     — 302 redirect pra signed URL R2 (TTL 5min)

Auth: cookie `cliente_session` valido (mesmo do /cliente/auth/me e /gate). User
sem cookie → 401. User cujo slug nao tem arquivo daquele dia → 404.

Anti-IDOR: nunca confia em path/query do client pra montar key R2 — sempre
deriva do `user.site_id` → `tenants_repo.obter_site(site_id).slug`. Cliente A
nao consegue baixar dia do cliente B (caso entrar uuid no path, nao da match).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask

from archiver import routes


def _criar_app(svc, tenants_repo, r2):
    app = Flask(__name__)
    app.config['TESTING'] = True
    routes.configurar(svc=svc, tenants_repo=tenants_repo, r2_client=r2)
    app.register_blueprint(routes.cliente_export_bp)
    return app


class _UserStub:
    def __init__(self, user_id='u1', site_id='site-uuid', email='x@y.com', papel='admin'):
        self.id = user_id
        self.site_id = site_id
        self.email = email
        self.papel = papel


class _SiteStub:
    def __init__(self, slug='acme'):
        self.slug = slug


class ClienteExportRoutesTest(unittest.TestCase):

    def setUp(self):
        self.svc = MagicMock()
        self.tenants_repo = MagicMock()
        self.r2 = MagicMock()
        self.app = _criar_app(self.svc, self.tenants_repo, self.r2)
        self.client = self.app.test_client()

    # --- GET /cliente/exportar (listagem) ---

    def test_listar_sem_cookie_401(self):
        self.svc.validar_cookie.return_value = None
        r = self.client.get('/cliente/exportar')
        self.assertEqual(r.status_code, 401)

    def test_listar_com_cookie_valido_retorna_keys_do_slug_do_user(self):
        self.svc.validar_cookie.return_value = _UserStub(site_id='site-1')
        self.tenants_repo.obter_site.return_value = _SiteStub(slug='acme')
        self.r2.listar_arquivos_do_slug.return_value = [
            'acme/2026/04/30.lp.gz',
            'acme/2026/05/01.lp.gz',
        ]

        r = self.client.get('/cliente/exportar', headers={'Cookie': 'cliente_session=ok'})

        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        # contrato: arquivos[].dia em ISO date, .bytes ausente (nao precisa GET por enquanto)
        self.assertEqual(len(body['arquivos']), 2)
        self.assertEqual(body['arquivos'][0]['dia'], '2026-04-30')
        self.assertEqual(body['arquivos'][1]['dia'], '2026-05-01')
        self.r2.listar_arquivos_do_slug.assert_called_once_with('acme')

    def test_listar_quando_site_nao_tem_slug_retorna_lista_vazia(self):
        self.svc.validar_cookie.return_value = _UserStub()
        self.tenants_repo.obter_site.return_value = None  # site removido?

        r = self.client.get('/cliente/exportar', headers={'Cookie': 'cliente_session=ok'})

        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['arquivos'], [])
        self.r2.listar_arquivos_do_slug.assert_not_called()

    # --- GET /cliente/exportar/<dia> (download) ---

    def test_download_sem_cookie_401(self):
        self.svc.validar_cookie.return_value = None
        r = self.client.get('/cliente/exportar/2026-04-30')
        self.assertEqual(r.status_code, 401)

    def test_download_dia_valido_redireciona_pra_signed_url(self):
        self.svc.validar_cookie.return_value = _UserStub()
        self.tenants_repo.obter_site.return_value = _SiteStub(slug='acme')
        self.r2.listar_arquivos_do_slug.return_value = ['acme/2026/04/30.lp.gz']
        self.r2.signed_url_para_download.return_value = 'https://r2.example/signed?X-Amz-Signature=abc'

        r = self.client.get('/cliente/exportar/2026-04-30', headers={'Cookie': 'cliente_session=ok'})

        self.assertEqual(r.status_code, 302)
        self.assertIn('signed', r.headers['Location'])
        self.r2.signed_url_para_download.assert_called_once_with(
            key='acme/2026/04/30.lp.gz',
            ttl_segundos=300,
        )

    def test_download_dia_inexistente_404(self):
        self.svc.validar_cookie.return_value = _UserStub()
        self.tenants_repo.obter_site.return_value = _SiteStub(slug='acme')
        self.r2.listar_arquivos_do_slug.return_value = ['acme/2026/04/30.lp.gz']

        r = self.client.get('/cliente/exportar/2026-12-31', headers={'Cookie': 'cliente_session=ok'})

        self.assertEqual(r.status_code, 404)
        self.r2.signed_url_para_download.assert_not_called()

    def test_download_dia_invalido_400(self):
        self.svc.validar_cookie.return_value = _UserStub()

        r = self.client.get('/cliente/exportar/abc', headers={'Cookie': 'cliente_session=ok'})

        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.get_json())

    def test_download_isola_clientes_nao_aceita_path_traversal_no_dia(self):
        # `dia` precisa bater regex YYYY-MM-DD. Nao se monta key com input do user.
        self.svc.validar_cookie.return_value = _UserStub()

        r = self.client.get(
            '/cliente/exportar/../outro-cliente/2026/04/30',
            headers={'Cookie': 'cliente_session=ok'},
        )
        self.assertNotEqual(r.status_code, 302)


if __name__ == '__main__':
    unittest.main()
