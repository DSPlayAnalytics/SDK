import os
import sys
import unittest

sys.path.append(os.path.dirname(__file__))

from ingestao.validador import validar_payload


def payload_valido():
    return {
        "id_registro": "sessao-xyz",
        "app_id": "teste",
        "ambiente": "production",
        "timestamp_inicial": 1760000000000,
        "timestamp_final": 1760000005000,
        "paginas": {
            "/": [
                {
                    "eventos": [
                        {"tipo": "page_view", "timestamp": 1760000000500, "dados": {"page_id": "/"}},
                        {"tipo": "click", "timestamp": 1760000001000, "dados": {"x": 10, "y": 20}},
                    ],
                    "visualizacoes": 1,
                    "segundos": 5,
                    "timestamp_inicial": 1760000000000,
                    "timestamp_final": 1760000005000,
                }
            ]
        },
    }


class ValidadorPayloadTest(unittest.TestCase):
    def test_payload_valido_canonico(self):
        ok, erros = validar_payload(payload_valido())
        self.assertTrue(ok)
        self.assertEqual(erros, [])

    def test_payload_aceita_paginas_vazio(self):
        data = payload_valido()
        data["paginas"] = {}
        ok, erros = validar_payload(data)
        self.assertTrue(ok)
        self.assertEqual(erros, [])

    def test_payload_ignora_campos_desconhecidos_no_envelope(self):
        data = payload_valido()
        data["app_id"] = "teste"
        data["ambiente"] = "production"
        data["campo_futuro"] = {"qualquer": "coisa"}
        ok, erros = validar_payload(data)
        self.assertTrue(ok)
        self.assertEqual(erros, [])

    def test_payload_ignora_campos_desconhecidos_no_evento(self):
        data = payload_valido()
        data["paginas"]["/"][0]["eventos"][0]["extra"] = 123
        ok, erros = validar_payload(data)
        self.assertTrue(ok)

    def test_rejeita_nao_dict(self):
        ok, erros = validar_payload("nao-e-dict")
        self.assertFalse(ok)
        self.assertIn("payload", erros[0])

    def test_rejeita_id_registro_ausente(self):
        data = payload_valido()
        data.pop("id_registro")
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("id_registro", erros)

    def test_rejeita_id_registro_vazio(self):
        data = payload_valido()
        data["id_registro"] = ""
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("id_registro", erros)

    def test_rejeita_timestamp_inicial_nao_numerico(self):
        data = payload_valido()
        data["timestamp_inicial"] = "agora"
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("timestamp_inicial", erros)

    def test_rejeita_timestamp_final_ausente(self):
        data = payload_valido()
        data.pop("timestamp_final")
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("timestamp_final", erros)

    def test_rejeita_paginas_nao_dict(self):
        data = payload_valido()
        data["paginas"] = [1, 2, 3]
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("paginas", erros)

    def test_rejeita_valor_de_pagina_nao_lista(self):
        data = payload_valido()
        data["paginas"]["/"] = {"eventos": []}
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("paginas./", erros)

    def test_rejeita_pagina_que_nao_e_objeto(self):
        data = payload_valido()
        data["paginas"]["/"] = ["nao-e-dict"]
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("paginas./[0]", erros)

    def test_rejeita_eventos_nao_lista(self):
        data = payload_valido()
        data["paginas"]["/"][0]["eventos"] = {}
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("paginas./[0].eventos", erros)

    def test_rejeita_evento_que_nao_e_objeto(self):
        data = payload_valido()
        data["paginas"]["/"][0]["eventos"][0] = "string"
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("paginas./[0].eventos[0]", erros)

    def test_rejeita_tipo_de_evento_fora_do_catalogo(self):
        data = payload_valido()
        data["paginas"]["/"][0]["eventos"][1]["tipo"] = "evento_inventado"
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("paginas./[0].eventos[1].tipo", erros)

    def test_rejeita_timestamp_de_evento_nao_numerico(self):
        data = payload_valido()
        data["paginas"]["/"][0]["eventos"][0]["timestamp"] = "agora"
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("paginas./[0].eventos[0].timestamp", erros)

    def test_acumula_multiplos_erros_em_uma_chamada(self):
        data = {
            "timestamp_final": "nao-numero",
            "paginas": {
                "/": [
                    {
                        "eventos": [
                            {"tipo": "invalido", "timestamp": 1000},
                            {"tipo": "click", "timestamp": "x"},
                        ],
                    }
                ]
            },
        }
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("id_registro", erros)
        self.assertIn("app_id", erros)
        self.assertIn("ambiente", erros)
        self.assertIn("timestamp_inicial", erros)
        self.assertIn("timestamp_final", erros)
        self.assertIn("paginas./[0].eventos[0].tipo", erros)
        self.assertIn("paginas./[0].eventos[1].timestamp", erros)

    def test_rejeita_app_id_ausente(self):
        data = payload_valido()
        data.pop("app_id")
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("app_id", erros)

    def test_rejeita_ambiente_invalido(self):
        data = payload_valido()
        data["ambiente"] = "homologacao"
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("ambiente", erros)

    def test_rejeita_ambiente_ausente(self):
        data = payload_valido()
        data.pop("ambiente")
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("ambiente", erros)


class ValidadorUserIdGroupIdTests(unittest.TestCase):
    """Schema 1.2 (SDK v0.4): user_id e group_id sao opcionais no envelope.

    Se presentes:
      - tipo string
      - 1..256 chars
      - charset: alfanum + `_-:.@` (`@` aceito porque cliente pode hashear
        email parcial; nao validamos PII server-side, so charset).
    Se ausentes ou null: payload aceito (forward-compat — SDK 1.1 nao manda).
    """

    def test_aceita_user_id_valido(self):
        data = payload_valido()
        data["user_id"] = "u-42"
        ok, erros = validar_payload(data)
        self.assertTrue(ok)
        self.assertEqual(erros, [])

    def test_aceita_group_id_valido(self):
        data = payload_valido()
        data["group_id"] = "acme-corp"
        ok, erros = validar_payload(data)
        self.assertTrue(ok)
        self.assertEqual(erros, [])

    def test_aceita_ambos(self):
        data = payload_valido()
        data["user_id"] = "u-42"
        data["group_id"] = "acme-corp"
        ok, erros = validar_payload(data)
        self.assertTrue(ok)
        self.assertEqual(erros, [])

    def test_aceita_user_id_ausente(self):
        # Forward-compat — SDK 1.1 nao manda user_id; nao deve quebrar.
        data = payload_valido()
        ok, erros = validar_payload(data)
        self.assertTrue(ok)
        self.assertNotIn("user_id", erros)

    def test_aceita_user_id_null(self):
        # SDK pode mandar null explicito apos reset() — equivalente a ausente.
        data = payload_valido()
        data["user_id"] = None
        ok, erros = validar_payload(data)
        self.assertTrue(ok)

    def test_aceita_user_id_max_256_chars(self):
        data = payload_valido()
        data["user_id"] = "u" * 256
        ok, erros = validar_payload(data)
        self.assertTrue(ok)

    def test_rejeita_user_id_acima_de_256(self):
        data = payload_valido()
        data["user_id"] = "u" * 257
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("user_id", erros)

    def test_rejeita_user_id_string_vazia(self):
        # String vazia explicita e diferente de ausente — sinaliza bug do
        # cliente. Rejeita pra detectar cedo.
        data = payload_valido()
        data["user_id"] = ""
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("user_id", erros)

    def test_rejeita_user_id_nao_string(self):
        data = payload_valido()
        data["user_id"] = 42
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("user_id", erros)

    def test_rejeita_user_id_com_quebra_de_linha(self):
        # Defesa contra log injection (\n no meio do user_id quebra parsing
        # de logs estruturados).
        data = payload_valido()
        data["user_id"] = "user\n42"
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("user_id", erros)

    def test_rejeita_user_id_com_caractere_proibido(self):
        # Charset: [A-Za-z0-9_\-:.@]. Espaco/acento/symbol fora.
        data = payload_valido()
        for invalido in ["user 42", "us€r", "u/42", "u<42>"]:
            with self.subTest(valor=invalido):
                data["user_id"] = invalido
                ok, erros = validar_payload(data)
                self.assertFalse(ok)
                self.assertIn("user_id", erros)

    def test_aceita_user_id_charset_completo(self):
        # Cobre as classes permitidas: alfanum + _ - : . @
        data = payload_valido()
        for valido in ["abc", "ABC", "123", "u_42", "u-42", "u:42", "u.42",
                       "user@hash.local", "0aF_-:.@"]:
            with self.subTest(valor=valido):
                data["user_id"] = valido
                ok, erros = validar_payload(data)
                self.assertTrue(ok, f"esperado aceitar {valido!r}, erros={erros}")

    def test_rejeita_group_id_acima_de_256(self):
        data = payload_valido()
        data["group_id"] = "g" * 257
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("group_id", erros)

    def test_rejeita_group_id_charset(self):
        data = payload_valido()
        data["group_id"] = "org com espaco"
        ok, erros = validar_payload(data)
        self.assertFalse(ok)
        self.assertIn("group_id", erros)


if __name__ == "__main__":
    unittest.main()
