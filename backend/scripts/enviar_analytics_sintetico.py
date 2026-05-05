import argparse
import json
import sys
import time
from pathlib import Path

import socketio


FIXTURE_PADRAO = Path(__file__).resolve().parents[1] / "fixtures" / "analytics_payload_sintetico.json"


def carregar_payload(caminho: Path) -> dict:
    with caminho.open(encoding="utf-8") as arquivo:
        return atualizar_timestamps(json.load(arquivo))


def atualizar_timestamps(payload: dict) -> dict:
    """Mantem duracoes do fixture, mas envia timestamps atuais para simular tempo real."""
    timestamp_final = int(time.time() * 1000)
    timestamp_inicial = timestamp_final - 7000
    payload["timestamp_inicial"] = timestamp_inicial
    payload["timestamp_final"] = timestamp_final

    for sessoes in payload.get("paginas", {}).values():
        for sessao in sessoes:
            offset_inicial = sessao["timestamp_inicial"] - 1760000000000
            offset_final = sessao["timestamp_final"] - 1760000000000
            sessao["timestamp_inicial"] = timestamp_inicial + offset_inicial
            sessao["timestamp_final"] = timestamp_inicial + offset_final

    return payload


def calcular_resumo_esperado(payload: dict) -> dict:
    paginas = payload.get("paginas", {})
    total_visualizacoes = 0
    total_cliques = 0
    tempo_total_segundos = 0
    paginas_visitadas = {}

    for page_id, sessoes in paginas.items():
        if isinstance(sessoes, dict):
            sessoes = [sessoes]
        paginas_visitadas[page_id] = len(sessoes)
        for sessao in sessoes:
            total_visualizacoes += int(sessao.get("visualizacoes", 0))
            total_cliques += len(sessao.get("cliques", []))
            tempo_total_segundos += int(sessao.get("segundos", 0))

    return {
        "total_visualizacoes": total_visualizacoes,
        "total_cliques": total_cliques,
        "tempo_total_segundos": tempo_total_segundos,
        "paginas_visitadas": paginas_visitadas,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Envia um payload sintetico de analytics via Socket.IO sem abrir a pagina web."
    )
    parser.add_argument("--url", default="http://localhost:5000", help="URL do backend Socket.IO.")
    parser.add_argument("--payload", default=str(FIXTURE_PADRAO), help="Arquivo JSON com payload analytics.")
    parser.add_argument(
        "--transport",
        choices=["polling", "websocket"],
        default="polling",
        help="Transporte Socket.IO. Use websocket somente se websocket-client estiver instalado.",
    )
    args = parser.parse_args()

    payload = carregar_payload(Path(args.payload))
    esperado = calcular_resumo_esperado(payload)
    sio = socketio.Client(logger=False, engineio_logger=False)
    respostas = []
    erros = []

    @sio.event
    def connect():
        print(f"Conectado em {args.url}")

    @sio.on("analytics_received")
    def analytics_received(data):
        respostas.append(data)
        print("analytics_received:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        sio.disconnect()

    @sio.on("analytics_error")
    def analytics_error(data):
        erros.append(data)
        print("analytics_error:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        sio.disconnect()

    sio.connect(
        args.url,
        headers={
            "User-Agent": "analytics-synthetic-client",
            "Accept-Language": "pt-BR",
        },
        transports=[args.transport],
        wait_timeout=10,
    )
    sio.emit("analytics_data", payload)
    sio.wait()

    if erros:
        return 1

    if not respostas:
        print("Nenhuma resposta analytics_received foi recebida.")
        return 1

    resumo_recebido = respostas[0].get("resumo", {})
    campos = ["total_visualizacoes", "total_cliques", "tempo_total_segundos", "paginas_visitadas"]
    divergencias = {
        campo: {"esperado": esperado[campo], "recebido": resumo_recebido.get(campo)}
        for campo in campos
        if resumo_recebido.get(campo) != esperado[campo]
    }

    if divergencias:
        print("Divergencias encontradas:")
        print(json.dumps(divergencias, indent=2, ensure_ascii=False))
        return 1

    print("Resumo recebido bate com o payload sintetico esperado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
