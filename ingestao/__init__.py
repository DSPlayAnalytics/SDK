"""Camada de ingestao: validacao + servico que isola handler Socket.IO da regra."""
from .validador import validar_payload, TIPOS_EVENTO_VALIDOS
from .servico_ingestao import ServicoIngestao, ResumoIngestao

__all__ = [
    'validar_payload',
    'TIPOS_EVENTO_VALIDOS',
    'ServicoIngestao',
    'ResumoIngestao',
]
