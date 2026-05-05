from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EventoNormalizado:
    """Evento normalizado emitido pelo SDK. `dados` carrega campos especificos por tipo."""
    tipo: str
    timestamp: int
    dados: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> 'EventoNormalizado':
        return cls(
            tipo=str(data.get('tipo', '')),
            timestamp=int(data.get('timestamp', 0)),
            dados=data.get('dados', {}) or {},
        )

    def to_dict(self) -> dict:
        return {
            'tipo': self.tipo,
            'timestamp': self.timestamp,
            'dados': self.dados,
        }


@dataclass
class PaginaDados:
    """Dados normalizados de uma pagina em uma janela de coleta."""
    eventos: List[EventoNormalizado] = field(default_factory=list)
    visualizacoes: int = 0
    segundos: int = 0
    timestamp_inicial: Optional[int] = None
    timestamp_final: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> 'PaginaDados':
        eventos_raw = data.get('eventos', []) or []
        eventos = [EventoNormalizado.from_dict(e) for e in eventos_raw if isinstance(e, dict)]
        return cls(
            eventos=eventos,
            visualizacoes=int(data.get('visualizacoes', 0)),
            segundos=int(data.get('segundos', 0)),
            timestamp_inicial=data.get('timestamp_inicial'),
            timestamp_final=data.get('timestamp_final'),
        )


@dataclass
class HeatmapDados:
    """Estrutura principal que organiza dados por pagina. Cada emissao representa um delta."""
    id_registro: str
    timestamp_inicial: Optional[int] = None
    timestamp_final: Optional[int] = None
    paginas: Dict[str, List[PaginaDados]] = None

    def __post_init__(self):
        if self.paginas is None:
            self.paginas = {}

    @classmethod
    def from_dict(cls, data: dict) -> 'HeatmapDados':
        paginas: Dict[str, List[PaginaDados]] = {}
        for page_id, page_data in (data.get('paginas') or {}).items():
            paginas[page_id] = cls._convert_lista_paginas(page_data)

        return cls(
            id_registro=data.get('id_registro', ''),
            timestamp_inicial=data.get('timestamp_inicial'),
            timestamp_final=data.get('timestamp_final'),
            paginas=paginas,
        )

    @classmethod
    def _convert_lista_paginas(cls, data) -> List[PaginaDados]:
        if not data:
            return []
        if isinstance(data, dict):
            return [PaginaDados.from_dict(data)]
        if isinstance(data, list):
            return [PaginaDados.from_dict(p) for p in data if isinstance(p, dict)]
        return []

    def to_dict(self) -> dict:
        return {
            'id_registro': self.id_registro,
            'timestamp_inicial': self.timestamp_inicial,
            'timestamp_final': self.timestamp_final,
            'paginas': {
                page_id: [
                    {
                        'eventos': [e.to_dict() for e in pagina.eventos],
                        'visualizacoes': pagina.visualizacoes,
                        'segundos': pagina.segundos,
                        'timestamp_inicial': pagina.timestamp_inicial,
                        'timestamp_final': pagina.timestamp_final,
                    }
                    for pagina in paginas
                ]
                for page_id, paginas in self.paginas.items()
            },
        }

    def get_total_visualizacoes(self) -> int:
        return sum(p.visualizacoes for paginas in self.paginas.values() for p in paginas)

    def get_total_cliques(self) -> int:
        return sum(
            1
            for paginas in self.paginas.values()
            for p in paginas
            for e in p.eventos
            if e.tipo == 'click'
        )

    def get_total_tempo_segundos(self) -> int:
        return sum(p.segundos for paginas in self.paginas.values() for p in paginas)

    def get_duracao_sessao_ms(self) -> Optional[int]:
        if self.timestamp_inicial and self.timestamp_final:
            return self.timestamp_final - self.timestamp_inicial
        return None

    def get_duracao_sessao_segundos(self) -> Optional[float]:
        duracao_ms = self.get_duracao_sessao_ms()
        if duracao_ms:
            return duracao_ms / 1000
        return None
