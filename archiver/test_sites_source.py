"""TDD da combinacao TenantsRepo+Quota em SiteArquivavel."""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archiver.scheduler import SiteArquivavel
from archiver.sites_source import listar_sites_arquivaveis


class _SiteStub:
    def __init__(self, id_, slug, plano='medio', status='ativo'):
        self.id = id_
        self.slug = slug
        self.plano = plano
        self.status = status


class _QuotaStub:
    def __init__(self, retencao_dias):
        self.retencao_dias = retencao_dias


class SitesSourceTest(unittest.TestCase):

    def test_filtra_inativos_e_combina_com_retencao(self):
        repo = MagicMock()
        repo.listar_sites.return_value = [
            _SiteStub('s1', 'acme', 'medio', 'ativo'),
            _SiteStub('s2', 'suspenso', 'medio', 'suspenso'),
            _SiteStub('s3', 'sem-slug', 'medio', 'ativo'),
        ]
        # repo retorna None se site nao tem quota — usa default 30d
        repo.obter_quota.side_effect = lambda sid: {'s1': _QuotaStub(90)}.get(sid)

        # mas s3 tem slug ('sem-slug') — nao e empty. Deixar passar.
        # se quisermos pular s3, regra e diferente. Aqui valida apenas que
        # filtra status != ativo.

        result = listar_sites_arquivaveis(repo)
        slugs = [s.slug for s in result]
        self.assertIn('acme', slugs)
        self.assertNotIn('suspenso', slugs)
        self.assertEqual(len(result), 2)

        acme = next(s for s in result if s.slug == 'acme')
        self.assertEqual(acme.retencao_dias, 90)

        sem_quota = next(s for s in result if s.slug == 'sem-slug')
        self.assertEqual(sem_quota.retencao_dias, 30)


if __name__ == '__main__':
    unittest.main()
