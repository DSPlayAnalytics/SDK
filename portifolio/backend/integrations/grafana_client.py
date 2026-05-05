"""Cliente HTTP minimal para Grafana — usado em provisionamento e sync de orgs.

Sem dependencia nova: stdlib `urllib.request`. Basic Auth admin obrigatorio.
Erros HTTP nao levantam excecao — sao retornados como dict com `__http_error__`
para o chamador decidir entre falha critica e idempotencia (ex: 409 ao criar
membership ja existente NAO eh erro).
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import quote


class GrafanaClient:
    def __init__(self, base_url: str, user: str, password: str, *, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.basic_auth = f"Basic {token}"
        self.timeout = timeout

    # ---------- baixo nivel ----------

    def _req(self, method: str, path: str, *, body: Optional[dict] = None,
             org_id: Optional[int] = None,
             expect_status: tuple[int, ...] = (200, 201)) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", self.basic_auth)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if org_id is not None:
            req.add_header("X-Grafana-Org-Id", str(org_id))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
                status = resp.status
                if status not in expect_status:
                    return {"__http_error__": status, "__body__": payload.decode(errors="replace")}
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode(errors="replace") if exc.fp else ""
            return {"__http_error__": exc.code, "__body__": payload}
        except (urllib.error.URLError, OSError) as exc:
            return {"__http_error__": -1, "__body__": str(exc)}

    @staticmethod
    def _quote(value: str) -> str:
        return quote(value, safe="")

    # ---------- orgs ----------

    def get_org_by_name(self, name: str) -> Optional[dict]:
        out = self._req("GET", f"/api/orgs/name/{self._quote(name)}", expect_status=(200,))
        if out.get("__http_error__") == 404:
            return None
        if "__http_error__" in out:
            raise RuntimeError(f"grafana GET /api/orgs/name failed: {out}")
        return out

    def create_org(self, name: str) -> int:
        out = self._req("POST", "/api/orgs", body={"name": name}, expect_status=(200,))
        if out.get("__http_error__") == 409:
            existing = self.get_org_by_name(name)
            if existing:
                return existing["id"]
            raise RuntimeError(f"grafana 409 ao criar org '{name}' mas GET nao encontrou")
        if "__http_error__" in out:
            raise RuntimeError(f"grafana POST /api/orgs failed: {out}")
        return out["orgId"]

    def get_or_create_org(self, name: str) -> int:
        existing = self.get_org_by_name(name)
        if existing:
            return existing["id"]
        return self.create_org(name)

    # ---------- users ----------

    def get_user_by_login(self, login: str) -> Optional[dict]:
        """Retorna user dict (com `id`) ou None se nao existe."""
        out = self._req("GET", f"/api/users/lookup?loginOrEmail={self._quote(login)}",
                        expect_status=(200,))
        if out.get("__http_error__") == 404:
            return None
        if "__http_error__" in out:
            raise RuntimeError(f"grafana GET /api/users/lookup failed: {out}")
        return out

    def add_org_user(self, org_id: int, *, login: str, role: str = "Viewer") -> bool:
        """Adiciona user a org. Retorna True se foi adicionado, False se ja era membro."""
        body = {"loginOrEmail": login, "role": role}
        out = self._req("POST", f"/api/orgs/{org_id}/users",
                        body=body, expect_status=(200,))
        if out.get("__http_error__") == 409:
            return False  # ja era membro
        if "__http_error__" in out:
            raise RuntimeError(f"grafana add_org_user failed: {out}")
        return True

    def remove_org_user(self, org_id: int, user_id: int) -> bool:
        """Remove user de uma org. Retorna False se nao era membro."""
        out = self._req("DELETE", f"/api/orgs/{org_id}/users/{user_id}",
                        expect_status=(200,))
        if out.get("__http_error__") == 404:
            return False
        if "__http_error__" in out:
            raise RuntimeError(f"grafana remove_org_user failed: {out}")
        return True

    def set_user_current_org(self, user_id: int, org_id: int) -> None:
        out = self._req("POST", f"/api/users/{user_id}/using/{org_id}",
                        expect_status=(200,))
        if "__http_error__" in out:
            raise RuntimeError(f"grafana set_user_current_org failed: {out}")

    # ---------- datasources ----------

    def get_datasource_by_name(self, name: str, *, org_id: int) -> Optional[dict]:
        out = self._req("GET", f"/api/datasources/name/{self._quote(name)}",
                        org_id=org_id, expect_status=(200,))
        if out.get("__http_error__") == 404:
            return None
        if "__http_error__" in out:
            raise RuntimeError(f"grafana GET datasource failed: {out}")
        return out

    # ---------- dashboards ----------

    def import_dashboard(self, *, org_id: int, dashboard: dict,
                         folder_uid: Optional[str] = None,
                         message: str = "provisioned by portifolio") -> dict:
        """Importa/atualiza dashboard idempotente via /api/dashboards/db.

        Comportamento:
          - Se o JSON tem `uid` setado e ja existe, faz overwrite (versao++).
          - Se nao tem `uid`, Grafana gera um novo (criacao).
          - O JSON deve ter `id: null` para evitar conflito entre orgs.

        Retorna `{"id": ..., "uid": ..., "url": ..., "version": ...}`.
        """
        body = {
            "dashboard": dashboard,
            "overwrite": True,
            "message": message,
        }
        if folder_uid is not None:
            body["folderUid"] = folder_uid
        out = self._req("POST", "/api/dashboards/db",
                        body=body, org_id=org_id, expect_status=(200,))
        if "__http_error__" in out:
            raise RuntimeError(f"grafana POST /api/dashboards/db failed: {out}")
        return out

    def upsert_influx_datasource(self, *, org_id: int, name: str, influx_url: str,
                                  influx_org: str, bucket: str, token: str) -> dict:
        body = {
            "name": name, "type": "influxdb", "access": "proxy", "url": influx_url,
            "isDefault": False,
            "jsonData": {
                "version": "Flux", "organization": influx_org,
                "defaultBucket": bucket, "tlsSkipVerify": False,
            },
            "secureJsonData": {"token": token}, "readOnly": False,
        }
        existing = self.get_datasource_by_name(name, org_id=org_id)
        if existing:
            uid = existing["uid"]
            body["uid"] = uid
            out = self._req("PUT", f"/api/datasources/uid/{uid}",
                            body=body, org_id=org_id, expect_status=(200,))
            if "__http_error__" in out:
                raise RuntimeError(f"grafana PUT datasource failed: {out}")
            return out["datasource"]
        out = self._req("POST", "/api/datasources",
                        body=body, org_id=org_id, expect_status=(200, 201))
        if "__http_error__" in out:
            raise RuntimeError(f"grafana POST datasource failed: {out}")
        return out["datasource"]
