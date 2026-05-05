"""CLI: roda `ingestao.validador.validar_payload` contra um arquivo JSON
e imprime erros. Retorna exit code 0 quando valido, 1 caso contrario.

Uso: python scripts/validar_fixture.py caminho/para/payload.json
"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from ingestao.validador import validar_payload  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('uso: validar_fixture.py <arquivo.json>', file=sys.stderr)
        return 2

    caminho = argv[1]
    if not os.path.isfile(caminho):
        print(f'arquivo nao encontrado: {caminho}', file=sys.stderr)
        return 2

    with open(caminho, 'r', encoding='utf-8') as arquivo:
        try:
            data = json.load(arquivo)
        except json.JSONDecodeError as erro:
            print(f'JSON invalido: {erro}', file=sys.stderr)
            return 2

    valido, erros = validar_payload(data)
    if valido:
        print(f'OK: {caminho} passa na validacao')
        return 0

    print(f'FAIL: {caminho} tem {len(erros)} problema(s):')
    for caminho_erro in erros:
        print(f'  - {caminho_erro}')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
