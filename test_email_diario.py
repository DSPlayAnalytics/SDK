"""TDD da lógica de email_diario.py.

Testa a função pura `executar_rodada_diaria` com dependências injetadas —
sem I/O real, sem banco, sem envio de email.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from auth.tenants_repo import Quota, Site
from auth.clientes_users_repo import ClienteUser
from scripts.email_diario import (
    executar_rodada_diaria,
    ResumoEmailDiario,
    THRESHOLD_AVISO,
    THRESHOLD_LIMITE,
)


# ─── helpers ────────────────────────────────────────────────────────────────

def _site(id: str, slug: str = "test", plano: str = "free", status: str = "ativo") -> Site:
    return Site(id=id, slug=slug, nome=slug, ambiente="production", plano=plano, status=status)


def _quota(site_id: str, eventos_por_dia: int = 1000) -> Quota:
    return Quota(
        site_id=site_id,
        eventos_por_minuto=60,
        eventos_por_dia=eventos_por_dia,
        emissoes_jwt_por_minuto=20,
        retencao_dias=30,
    )


def _user(site_id: str, email: str) -> ClienteUser:
    return ClienteUser(id="u-" + site_id, site_id=site_id, email=email,
                       papel="owner", ativo=True, senha_hash=None, ultimo_login=None)


class FakeTenantsRepo:
    def __init__(self, sites: List[Site], quotas: Dict[str, Quota], consumos: Dict[str, int]):
        self._sites = sites
        self._quotas = quotas
        self._consumos = consumos  # site_id -> consumo no dia referencia

    def listar_sites(self):
        return self._sites

    def obter_quota(self, site_id):
        return self._quotas.get(site_id)

    def consumo_em_dia(self, site_id, dia):
        return self._consumos.get(site_id, 0)


class FakeUsersRepo:
    def __init__(self, users: Dict[str, Optional[ClienteUser]]):
        self._users = users  # site_id -> user (or None)

    def obter_user_por_site(self, site_id):
        return self._users.get(site_id)


class FakeSender:
    def __init__(self, fail_for: frozenset = frozenset()):
        self.enviados: List[dict] = []
        self._fail_for = fail_for

    def enviar(self, *, destinatario, assunto, corpo_texto, corpo_html=None) -> bool:
        if destinatario in self._fail_for:
            return False
        self.enviados.append({"destinatario": destinatario, "assunto": assunto, "corpo": corpo_texto})
        return True


ONTEM = date(2026, 5, 1)


# ─── testes ────────────────────────────────────────────────────────────────

class TestThresholds:
    def test_threshold_aviso_is_80_pct(self):
        assert THRESHOLD_AVISO == 0.80

    def test_threshold_limite_is_100_pct(self):
        assert THRESHOLD_LIMITE == 1.00


class TestSitesSemAtividade:
    def test_consumo_zero_nao_envia(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1")],
            quotas={"s1": _quota("s1")},
            consumos={"s1": 0},
        )
        users = FakeUsersRepo({"s1": _user("s1", "a@b.com")})
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 0
        assert resumo.pulados == 1
        assert len(sender.enviados) == 0

    def test_consumo_abaixo_aviso_nao_envia(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1")],
            quotas={"s1": _quota("s1", eventos_por_dia=1000)},
            consumos={"s1": 799},
        )
        users = FakeUsersRepo({"s1": _user("s1", "a@b.com")})
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 0
        assert resumo.pulados == 1


class TestAvisoProximoQuota:
    def test_consumo_exatamente_80pct_envia_aviso(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1")],
            quotas={"s1": _quota("s1", eventos_por_dia=1000)},
            consumos={"s1": 800},
        )
        users = FakeUsersRepo({"s1": _user("s1", "alerta@exemplo.com")})
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 1
        assert sender.enviados[0]["destinatario"] == "alerta@exemplo.com"
        assert "800" in sender.enviados[0]["corpo"]
        assert "000" in sender.enviados[0]["corpo"]  # parte de "1000" ou "1,000"

    def test_consumo_85pct_envia_aviso(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1")],
            quotas={"s1": _quota("s1", eventos_por_dia=1000)},
            consumos={"s1": 850},
        )
        users = FakeUsersRepo({"s1": _user("s1", "x@y.com")})
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 1
        corpo = sender.enviados[0]["corpo"]
        assert "85%" in corpo or "85,0%" in corpo

    def test_assunto_aviso_menciona_site(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1", slug="minha-loja")],
            quotas={"s1": _quota("s1", eventos_por_dia=1000)},
            consumos={"s1": 850},
        )
        users = FakeUsersRepo({"s1": _user("s1", "x@y.com")})
        sender = FakeSender()

        executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert "minha-loja" in sender.enviados[0]["assunto"]


class TestLimiteAtingido:
    def test_consumo_100pct_envia_alerta_limite(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1")],
            quotas={"s1": _quota("s1", eventos_por_dia=500)},
            consumos={"s1": 500},
        )
        users = FakeUsersRepo({"s1": _user("s1", "dono@site.com")})
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 1
        corpo = sender.enviados[0]["corpo"]
        assert "100%" in corpo or "limite" in corpo.lower()

    def test_consumo_acima_limite_envia_alerta(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1")],
            quotas={"s1": _quota("s1", eventos_por_dia=1000)},
            consumos={"s1": 1200},
        )
        users = FakeUsersRepo({"s1": _user("s1", "dono@site.com")})
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 1


class TestEdgeCases:
    def test_site_sem_user_pula(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1")],
            quotas={"s1": _quota("s1")},
            consumos={"s1": 900},
        )
        users = FakeUsersRepo({"s1": None})
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 0
        assert resumo.sem_email == 1

    def test_site_sem_quota_pula(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1")],
            quotas={},
            consumos={"s1": 900},
        )
        users = FakeUsersRepo({"s1": _user("s1", "x@y.com")})
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 0
        assert resumo.pulados == 1

    def test_site_inativo_pula(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1", status="suspenso")],
            quotas={"s1": _quota("s1")},
            consumos={"s1": 900},
        )
        users = FakeUsersRepo({"s1": _user("s1", "x@y.com")})
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 0
        assert resumo.pulados == 1

    def test_falha_envio_contabiliza_falha(self):
        tenants = FakeTenantsRepo(
            sites=[_site("s1")],
            quotas={"s1": _quota("s1")},
            consumos={"s1": 850},
        )
        users = FakeUsersRepo({"s1": _user("s1", "fail@exemplo.com")})
        sender = FakeSender(fail_for=frozenset(["fail@exemplo.com"]))

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 0
        assert resumo.falhas == 1

    def test_multiplos_sites_independentes(self):
        tenants = FakeTenantsRepo(
            sites=[
                _site("s1", slug="alto"),  # 90% — aviso
                _site("s2", slug="baixo"),  # 10% — ignora
                _site("s3", slug="cheio"),  # 100% — limite
            ],
            quotas={
                "s1": _quota("s1", eventos_por_dia=1000),
                "s2": _quota("s2", eventos_por_dia=1000),
                "s3": _quota("s3", eventos_por_dia=1000),
            },
            consumos={"s1": 900, "s2": 100, "s3": 1000},
        )
        users = FakeUsersRepo({
            "s1": _user("s1", "alto@a.com"),
            "s2": _user("s2", "baixo@b.com"),
            "s3": _user("s3", "cheio@c.com"),
        })
        sender = FakeSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 2  # alto + cheio
        assert resumo.pulados == 1   # baixo

    def test_excecao_em_sender_nao_para_loop(self):
        """Se o sender explodir, captura e continua."""
        tenants = FakeTenantsRepo(
            sites=[_site("s1"), _site("s2")],
            quotas={"s1": _quota("s1"), "s2": _quota("s2")},
            consumos={"s1": 900, "s2": 900},
        )
        users = FakeUsersRepo({
            "s1": _user("s1", "a@a.com"),
            "s2": _user("s2", "b@b.com"),
        })

        class BoomSender:
            def __init__(self):
                self.enviados = []
                self._call = 0

            def enviar(self, *, destinatario, assunto, corpo_texto, corpo_html=None):
                self._call += 1
                if self._call == 1:
                    raise RuntimeError("rede morta")
                self.enviados.append(destinatario)
                return True

        sender = BoomSender()

        resumo = executar_rodada_diaria(tenants, users, sender, ONTEM)

        assert resumo.enviados == 1
        assert resumo.falhas == 1
