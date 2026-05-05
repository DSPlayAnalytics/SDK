"""Abstracao minima de envio de e-mail para magic-links.

Duas implementacoes concretas:
  - `EmailStdoutSender` — dev/teste; imprime no stdout com logging estruturado.
  - `ResendEmailSender` — producao; POST para a API do Resend.

A escolha acontece em tempo de configuracao (ENV `EMAIL_PROVIDER` ou explicita).
Se `RESEND_API_KEY` nao estiver setada, fallback automatico pro stdout — util
para dev local sem precisar de conta.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol


logger = logging.getLogger("auth.email")


class EmailSender(Protocol):
    def enviar(self, *, destinatario: str, assunto: str, corpo_texto: str,
               corpo_html: str | None = None) -> bool: ...


class EmailStdoutSender:
    """Imprime o email no log em vez de enviar. Usado em dev/teste."""

    def enviar(self, *, destinatario, assunto, corpo_texto, corpo_html=None) -> bool:
        logger.info(
            "evento=email_stdout destinatario=%s assunto=%r corpo=%r",
            destinatario, assunto, corpo_texto,
        )
        return True


class ResendEmailSender:
    """Envio via Resend (https://resend.com/docs/api-reference)."""

    _URL = "https://api.resend.com/emails"

    def __init__(self, api_key: str, *, from_addr: str):
        if not api_key:
            raise ValueError("RESEND_API_KEY vazio")
        self._api_key = api_key
        self._from = from_addr

    def enviar(self, *, destinatario, assunto, corpo_texto, corpo_html=None) -> bool:
        # Import tardio — urllib3 ja esta no stack (vem com requests/Werkzeug).
        import urllib.request
        import urllib.error

        payload = {
            "from": self._from,
            "to": [destinatario],
            "subject": assunto,
            "text": corpo_texto,
        }
        if corpo_html:
            payload["html"] = corpo_html

        req = urllib.request.Request(
            self._URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                # CF na frente da api.resend.com bane User-Agent generico
                # do urllib (Python-urllib/3.X) com error 1010. Identificacao
                # explicita evita o bloqueio.
                "User-Agent": "dsplayground-backend/1.0 (+https://dsplayground.com.br)",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                ok = 200 <= resp.status < 300
                logger.info(
                    "evento=email_resend destinatario=%s status=%d ok=%s",
                    destinatario, resp.status, ok,
                )
                return ok
        except urllib.error.HTTPError as e:
            logger.warning(
                "evento=email_resend_fail destinatario=%s status=%d body=%r",
                destinatario, e.code, e.read()[:500],
            )
            return False
        except Exception as e:  # rede/timeout
            logger.warning("evento=email_resend_erro destinatario=%s erro=%r", destinatario, e)
            return False


def criar_sender_padrao() -> EmailSender:
    """Escolhe o sender baseado em ENV. Stdout se RESEND_API_KEY ausente."""
    chave = os.environ.get("RESEND_API_KEY", "").strip()
    remetente = os.environ.get("EMAIL_FROM", "no-reply@dsplayground.com.br")
    if chave:
        return ResendEmailSender(chave, from_addr=remetente)
    logger.info("evento=email_sender_fallback provider=stdout motivo=RESEND_API_KEY ausente")
    return EmailStdoutSender()


__all__ = ["EmailSender", "EmailStdoutSender", "ResendEmailSender", "criar_sender_padrao"]
