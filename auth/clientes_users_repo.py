"""Repositorio de usuarios humanos do dashboard por cliente (site).

Separacao de responsabilidades versus `tenants_repo.py`:
  - `tenants_repo`     -> auth do SDK de ingest (publishable keys + JWT write-only)
  - `clientes_users_*` -> auth humana do dashboard (email + cookie read-only)

Duas implementacoes com interface unica (seguindo o padrao de tenants_repo):
  - `SqliteClientesUsersRepo` — testes e dev local.
  - `PostgresClientesUsersRepo` — producao, psycopg v3 com pool.

Toda comparacao de email e case-insensitive (normalizada em lowercase antes
de persistir). Token de sessao e magic-link sao sempre armazenados como
sha256 hex — plaintext nunca persiste.

Referencia: ark/docs/dashboard-cliente.md (secoes 5 e 6).
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Protocol


SCHEMA_SQLITE_PATH = Path(__file__).resolve().parent / "schema_dashboard.sql"
SCHEMA_POSTGRES_PATH = Path(__file__).resolve().parent / "schema_dashboard_postgres.sql"


def hash_token(plaintext: str) -> str:
    """Hash sha256 hex de um token (cookie de sessao ou magic-link).

    Server nunca deve persistir o token plaintext; sempre este hash.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def normalizar_email(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class ClienteUser:
    id: str
    site_id: str
    email: str
    senha_hash: Optional[str]
    papel: str
    ativo: bool
    ultimo_login: Optional[datetime]


@dataclass(frozen=True)
class Sessao:
    id: str
    user_id: str
    token_hash: str
    ip: Optional[str]
    user_agent: Optional[str]
    expira_em: datetime
    revogada_em: Optional[datetime]


@dataclass(frozen=True)
class MagicLink:
    id: str
    user_id: str
    token_hash: str
    expira_em: datetime
    consumido_em: Optional[datetime]
    ip_solicitacao: Optional[str]
    # 'login' (legado/default — entra direto no dashboard ao consumir)
    # 'reset' (consumir nao cria sessao; redireciona pra form de nova senha
    #          servida pela landing; sessao so e criada apos POST /confirmar)
    tipo: str = "login"


# ---------- interface comum ----------

class ClientesUsersRepo(Protocol):
    # users
    def criar_user(self, site_id: str, email: str, *, papel: str = "viewer",
                   senha_hash: Optional[str] = None) -> ClienteUser: ...
    def obter_user(self, user_id: str) -> Optional[ClienteUser]: ...
    def obter_user_por_email(self, email: str) -> Optional[ClienteUser]: ...
    def obter_user_por_site(self, site_id: str) -> Optional[ClienteUser]: ...
    def registrar_login(self, user_id: str) -> None: ...
    def desativar_user(self, user_id: str) -> None: ...
    def atualizar_senha_hash(self, user_id: str, senha_hash: str) -> None: ...
    def atualizar_email(self, user_id: str, novo_email: str) -> None: ...

    # sessoes
    def criar_sessao(self, user_id: str, token_hash: str, *,
                     expira_em: datetime, ip: Optional[str] = None,
                     user_agent: Optional[str] = None) -> Sessao: ...
    def obter_sessao_por_hash(self, token_hash: str) -> Optional[Sessao]: ...
    def revogar_sessao(self, token_hash: str) -> None: ...
    def limpar_sessoes_expiradas(self) -> int: ...

    # magic-links
    def criar_magic_link(self, user_id: str, token_hash: str, *,
                         expira_em: datetime,
                         ip: Optional[str] = None,
                         tipo: str = "login") -> MagicLink: ...
    def obter_magic_link_por_hash(self, token_hash: str) -> Optional[MagicLink]: ...
    def consumir_magic_link(self, token_hash: str) -> bool: ...
    def contar_magic_links_recentes(self, user_id: str, janela_segundos: int) -> int: ...
    def contar_magic_links_por_ip(self, ip: str, janela_segundos: int) -> int: ...


# ======================================================================
#                            SQLite
# ======================================================================


class SqliteClientesUsersRepo:
    """SQLite — testes e dev local. Compartilha o DB path com SqliteTenantsRepo
    porque clientes_users tem FK para sites(id).
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.RLock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        schema = SCHEMA_SQLITE_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, isolation_level=None, timeout=10.0)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        return conn

    # users
    def criar_user(self, site_id, email, *, papel="viewer", senha_hash=None):
        user_id = str(uuid.uuid4())
        email_norm = normalizar_email(email)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO clientes_users (id, site_id, email, senha_hash, papel) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, site_id, email_norm, senha_hash, papel),
            )
        return ClienteUser(
            id=user_id, site_id=site_id, email=email_norm,
            senha_hash=senha_hash, papel=papel, ativo=True, ultimo_login=None,
        )

    def obter_user(self, user_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM clientes_users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_user(row) if row else None

    def obter_user_por_email(self, email):
        email_norm = normalizar_email(email)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM clientes_users WHERE email = ? COLLATE NOCASE",
                (email_norm,),
            ).fetchone()
        return _row_to_user(row) if row else None

    def obter_user_por_site(self, site_id: str) -> Optional[ClienteUser]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM clientes_users WHERE site_id = ? AND ativo = 1 "
                "ORDER BY criado_em LIMIT 1",
                (site_id,),
            ).fetchone()
        return _row_to_user(row) if row else None

    def registrar_login(self, user_id):
        agora = _iso(datetime.now(timezone.utc))
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE clientes_users SET ultimo_login = ? WHERE id = ?",
                         (agora, user_id))

    def desativar_user(self, user_id):
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE clientes_users SET ativo = 0 WHERE id = ?", (user_id,))

    def atualizar_senha_hash(self, user_id, senha_hash):
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE clientes_users SET senha_hash = ? WHERE id = ?",
                         (senha_hash, user_id))

    def atualizar_email(self, user_id, novo_email):
        # UNIQUE(email) sobe IntegrityError se conflitar — caller decide se converte em codigo de erro.
        email_norm = normalizar_email(novo_email)
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE clientes_users SET email = ? WHERE id = ?",
                         (email_norm, user_id))

    # sessoes
    def criar_sessao(self, user_id, token_hash, *, expira_em, ip=None, user_agent=None):
        sessao_id = str(uuid.uuid4())
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO clientes_users_sessoes "
                "(id, user_id, token_hash, ip, user_agent, expira_em) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (sessao_id, user_id, token_hash, ip, user_agent, _iso(expira_em)),
            )
        return Sessao(
            id=sessao_id, user_id=user_id, token_hash=token_hash,
            ip=ip, user_agent=user_agent, expira_em=expira_em, revogada_em=None,
        )

    def obter_sessao_por_hash(self, token_hash):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM clientes_users_sessoes WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return _row_to_sessao(row) if row else None

    def revogar_sessao(self, token_hash):
        agora = _iso(datetime.now(timezone.utc))
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE clientes_users_sessoes SET revogada_em = ? "
                "WHERE token_hash = ? AND revogada_em IS NULL",
                (agora, token_hash),
            )

    def limpar_sessoes_expiradas(self):
        agora = _iso(datetime.now(timezone.utc))
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM clientes_users_sessoes WHERE expira_em < ? OR revogada_em IS NOT NULL",
                (agora,),
            )
            return cur.rowcount or 0

    # magic-links
    def criar_magic_link(self, user_id, token_hash, *, expira_em, ip=None, tipo="login"):
        magic_id = str(uuid.uuid4())
        if tipo not in ("login", "reset"):
            raise ValueError(f"tipo invalido: {tipo}")
        # Migracao SQLite — coluna `tipo` adicionada em 2026-05-02 no
        # esquema; DBs pre-fix nao tem. PRAGMA table_info verifica e
        # ALTER TABLE adiciona on-the-fly.
        with self._lock, self._connect() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(clientes_magic_links)")}
            if "tipo" not in cols:
                conn.execute(
                    "ALTER TABLE clientes_magic_links "
                    "ADD COLUMN tipo TEXT NOT NULL DEFAULT 'login'"
                )
            conn.execute(
                "INSERT INTO clientes_magic_links "
                "(id, user_id, token_hash, expira_em, ip_solicitacao, tipo) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (magic_id, user_id, token_hash, _iso(expira_em), ip, tipo),
            )
        return MagicLink(
            id=magic_id, user_id=user_id, token_hash=token_hash,
            expira_em=expira_em, consumido_em=None, ip_solicitacao=ip, tipo=tipo,
        )

    def obter_magic_link_por_hash(self, token_hash):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM clientes_magic_links WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return _row_to_magic(row) if row else None

    def consumir_magic_link(self, token_hash):
        agora = _iso(datetime.now(timezone.utc))
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE clientes_magic_links SET consumido_em = ? "
                "WHERE token_hash = ? AND consumido_em IS NULL AND expira_em > ?",
                (agora, token_hash, agora),
            )
            return (cur.rowcount or 0) > 0

    def contar_magic_links_recentes(self, user_id, janela_segundos):
        from datetime import timedelta
        corte = _iso(datetime.now(timezone.utc) - timedelta(seconds=janela_segundos))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM clientes_magic_links "
                "WHERE user_id = ? AND criada_em >= ?",
                (user_id, corte),
            ).fetchone()
        return int(row["total"]) if row else 0

    def contar_magic_links_por_ip(self, ip, janela_segundos):
        from datetime import timedelta
        corte = _iso(datetime.now(timezone.utc) - timedelta(seconds=janela_segundos))
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM clientes_magic_links "
                "WHERE ip_solicitacao = ? AND criada_em >= ?",
                (ip, corte),
            ).fetchone()
        return int(row["total"]) if row else 0


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_iso(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _row_to_user(row: sqlite3.Row) -> ClienteUser:
    return ClienteUser(
        id=row["id"], site_id=row["site_id"], email=row["email"],
        senha_hash=row["senha_hash"], papel=row["papel"],
        ativo=bool(row["ativo"]), ultimo_login=_parse_iso(row["ultimo_login"]),
    )


def _row_to_sessao(row: sqlite3.Row) -> Sessao:
    return Sessao(
        id=row["id"], user_id=row["user_id"], token_hash=row["token_hash"],
        ip=row["ip"], user_agent=row["user_agent"],
        expira_em=_parse_iso(row["expira_em"]),
        revogada_em=_parse_iso(row["revogada_em"]),
    )


def _row_to_magic(row: sqlite3.Row) -> MagicLink:
    keys = row.keys()
    tipo = row["tipo"] if "tipo" in keys else "login"
    return MagicLink(
        id=row["id"], user_id=row["user_id"], token_hash=row["token_hash"],
        expira_em=_parse_iso(row["expira_em"]),
        consumido_em=_parse_iso(row["consumido_em"]),
        ip_solicitacao=row["ip_solicitacao"],
        tipo=tipo,
    )


# ======================================================================
#                            Postgres
# ======================================================================


class PostgresClientesUsersRepo:
    """Implementacao Postgres (producao). Mesma interface, `%s` como placeholder."""

    def __init__(self, dsn: str, *, pool_min: int = 1, pool_max: int = 10):
        from psycopg_pool import ConnectionPool
        from psycopg.rows import dict_row

        self._pool = ConnectionPool(
            conninfo=dsn, min_size=pool_min, max_size=pool_max,
            open=True, kwargs={"row_factory": dict_row},
        )
        schema = SCHEMA_POSTGRES_PATH.read_text(encoding="utf-8")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(schema)

    @contextmanager
    def _conn(self) -> Iterator:
        with self._pool.connection() as conn:
            yield conn

    # users
    def criar_user(self, site_id, email, *, papel="viewer", senha_hash=None):
        user_id = str(uuid.uuid4())
        email_norm = normalizar_email(email)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clientes_users (id, site_id, email, senha_hash, papel) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, site_id, email_norm, senha_hash, papel),
            )
        return ClienteUser(
            id=user_id, site_id=site_id, email=email_norm,
            senha_hash=senha_hash, papel=papel, ativo=True, ultimo_login=None,
        )

    def obter_user(self, user_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM clientes_users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        return _dict_to_user(row) if row else None

    def obter_user_por_email(self, email):
        email_norm = normalizar_email(email)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM clientes_users WHERE LOWER(email) = %s", (email_norm,))
            row = cur.fetchone()
        return _dict_to_user(row) if row else None

    def obter_user_por_site(self, site_id: str) -> Optional[ClienteUser]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM clientes_users WHERE site_id = %s AND ativo = true "
                "ORDER BY criado_em LIMIT 1",
                (site_id,),
            )
            row = cur.fetchone()
        return _dict_to_user(row) if row else None

    def registrar_login(self, user_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE clientes_users SET ultimo_login = NOW() WHERE id = %s", (user_id,))

    def desativar_user(self, user_id):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE clientes_users SET ativo = false WHERE id = %s", (user_id,))

    def atualizar_senha_hash(self, user_id, senha_hash):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE clientes_users SET senha_hash = %s WHERE id = %s",
                        (senha_hash, user_id))

    def atualizar_email(self, user_id, novo_email):
        email_norm = normalizar_email(novo_email)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE clientes_users SET email = %s WHERE id = %s",
                        (email_norm, user_id))

    # sessoes
    def criar_sessao(self, user_id, token_hash, *, expira_em, ip=None, user_agent=None):
        sessao_id = str(uuid.uuid4())
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clientes_users_sessoes "
                "(id, user_id, token_hash, ip, user_agent, expira_em) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (sessao_id, user_id, token_hash, ip, user_agent, expira_em),
            )
        return Sessao(
            id=sessao_id, user_id=user_id, token_hash=token_hash,
            ip=ip, user_agent=user_agent, expira_em=expira_em, revogada_em=None,
        )

    def obter_sessao_por_hash(self, token_hash):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM clientes_users_sessoes WHERE token_hash = %s", (token_hash,))
            row = cur.fetchone()
        return _dict_to_sessao(row) if row else None

    def revogar_sessao(self, token_hash):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE clientes_users_sessoes SET revogada_em = NOW() "
                "WHERE token_hash = %s AND revogada_em IS NULL",
                (token_hash,),
            )

    def limpar_sessoes_expiradas(self):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM clientes_users_sessoes "
                "WHERE expira_em < NOW() OR revogada_em IS NOT NULL"
            )
            return cur.rowcount or 0

    # magic-links
    def criar_magic_link(self, user_id, token_hash, *, expira_em, ip=None, tipo="login"):
        if tipo not in ("login", "reset"):
            raise ValueError(f"tipo invalido: {tipo}")
        magic_id = str(uuid.uuid4())
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clientes_magic_links "
                "(id, user_id, token_hash, expira_em, ip_solicitacao, tipo) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (magic_id, user_id, token_hash, expira_em, ip, tipo),
            )
        return MagicLink(
            id=magic_id, user_id=user_id, token_hash=token_hash,
            expira_em=expira_em, consumido_em=None, ip_solicitacao=ip, tipo=tipo,
        )

    def obter_magic_link_por_hash(self, token_hash):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM clientes_magic_links WHERE token_hash = %s", (token_hash,))
            row = cur.fetchone()
        return _dict_to_magic(row) if row else None

    def consumir_magic_link(self, token_hash):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE clientes_magic_links SET consumido_em = NOW() "
                "WHERE token_hash = %s AND consumido_em IS NULL AND expira_em > NOW()",
                (token_hash,),
            )
            return (cur.rowcount or 0) > 0

    def contar_magic_links_recentes(self, user_id, janela_segundos):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM clientes_magic_links "
                "WHERE user_id = %s AND criada_em >= NOW() - (%s || ' seconds')::INTERVAL",
                (user_id, str(janela_segundos)),
            )
            row = cur.fetchone()
        return int(row["total"]) if row else 0

    def contar_magic_links_por_ip(self, ip, janela_segundos):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total FROM clientes_magic_links "
                "WHERE ip_solicitacao = %s AND criada_em >= NOW() - (%s || ' seconds')::INTERVAL",
                (ip, str(janela_segundos)),
            )
            row = cur.fetchone()
        return int(row["total"]) if row else 0


def _dict_to_user(row: dict) -> ClienteUser:
    return ClienteUser(
        id=str(row["id"]), site_id=str(row["site_id"]), email=row["email"],
        senha_hash=row["senha_hash"], papel=row["papel"],
        ativo=bool(row["ativo"]), ultimo_login=row["ultimo_login"],
    )


def _dict_to_sessao(row: dict) -> Sessao:
    return Sessao(
        id=str(row["id"]), user_id=str(row["user_id"]), token_hash=row["token_hash"],
        ip=row["ip"], user_agent=row["user_agent"],
        expira_em=row["expira_em"], revogada_em=row["revogada_em"],
    )


def _dict_to_magic(row: dict) -> MagicLink:
    return MagicLink(
        id=str(row["id"]), user_id=str(row["user_id"]), token_hash=row["token_hash"],
        expira_em=row["expira_em"], consumido_em=row["consumido_em"],
        ip_solicitacao=row["ip_solicitacao"],
        tipo=row.get("tipo") or "login",
    )


# ======================================================================
#                        factory + singleton
# ======================================================================


def criar_clientes_users_repo(url: str) -> ClientesUsersRepo:
    """Mesma convencao de `criar_tenants_repo`: `postgresql://...` ou path sqlite."""
    if url.startswith(("postgresql://", "postgres://")):
        return PostgresClientesUsersRepo(url)
    if url.startswith("sqlite:///"):
        return SqliteClientesUsersRepo(url[len("sqlite:///"):])
    return SqliteClientesUsersRepo(url)


_repo_instance: Optional[ClientesUsersRepo] = None
_repo_lock = threading.Lock()


def obter_repo(url: Optional[str] = None) -> ClientesUsersRepo:
    global _repo_instance
    with _repo_lock:
        if _repo_instance is None:
            if url is None:
                raise RuntimeError(
                    "ClientesUsersRepo nao inicializado; passe url/path na 1a chamada"
                )
            _repo_instance = criar_clientes_users_repo(url)
        return _repo_instance


def resetar_repo() -> None:
    """Apenas para testes."""
    global _repo_instance
    with _repo_lock:
        _repo_instance = None
