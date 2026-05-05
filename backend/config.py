import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")


def obter_bool(nome_variavel: str, padrao: str = "false") -> bool:
    return os.environ.get(nome_variavel, padrao).strip().lower() == "true"


def obter_lista(nome_variavel: str, padrao: str = "") -> list[str]:
    valor = os.environ.get(nome_variavel, padrao)
    return [item.strip() for item in valor.split(",") if item.strip()]


def exigir_variavel(nome_variavel: str) -> str:
    valor = os.environ.get(nome_variavel)
    if not valor:
        raise RuntimeError(f"Variavel de ambiente obrigatoria ausente: {nome_variavel}")
    return valor


class Config:
    """Configuracao base carregada exclusivamente por variaveis de ambiente."""

    SECRET_KEY = exigir_variavel("SECRET_KEY")
    DEBUG = False
    TESTING = False

    TEMPORAL_REALTIME_INTERVAL = int(os.environ.get("TEMPORAL_REALTIME_INTERVAL", "5000"))
    TEMPORAL_REGULAR_INTERVAL = int(os.environ.get("TEMPORAL_REGULAR_INTERVAL", "15000"))
    TEMPORAL_CACHE_SIZE = int(os.environ.get("TEMPORAL_CACHE_SIZE", "1000"))
    TEMPORAL_CLEANUP_INTERVAL = int(os.environ.get("TEMPORAL_CLEANUP_INTERVAL", "300"))

    INFLUXDB_ENABLED = obter_bool("INFLUXDB_ENABLED")
    INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "")
    INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN", "")
    INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG", "")
    INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "")

    if INFLUXDB_ENABLED:
        INFLUXDB_URL = exigir_variavel("INFLUXDB_URL")
        INFLUXDB_TOKEN = exigir_variavel("INFLUXDB_TOKEN")
        INFLUXDB_ORG = exigir_variavel("INFLUXDB_ORG")
        INFLUXDB_BUCKET = exigir_variavel("INFLUXDB_BUCKET")

    CORS_ORIGINS = obter_lista("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "5000"))

    # Autenticacao multi-tenant do SDK
    JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "api.dsplayground.local")
    JWT_KEYS_DIR = os.environ.get("JWT_KEYS_DIR", str(Path(__file__).resolve().parent / "data" / "keys"))
    # URL do banco relacional de tenants.
    #   Producao/compose: `postgresql://user:pass@postgres:5432/portifolio_auth`
    #   Dev/testes sem container: `sqlite:///...` ou path absoluto para arquivo .db
    TENANTS_DATABASE_URL = os.environ.get(
        "TENANTS_DATABASE_URL",
        "sqlite:///" + str(Path(__file__).resolve().parent / "data" / "tenants.db"),
    )
    SDK_TOKEN_TTL_SECONDS = int(os.environ.get("SDK_TOKEN_TTL_SECONDS", "300"))
    SDK_TOKEN_RATE_LIMIT_PER_KEY = int(os.environ.get("SDK_TOKEN_RATE_LIMIT_PER_KEY", "5"))
    # Se True, conexoes Socket.IO sem sdk_jwt valido sao rejeitadas.
    # Durante a migracao (SDK ainda sem suporte a token) deixar False.
    SDK_AUTH_REQUIRED = obter_bool("SDK_AUTH_REQUIRED", "false")

    # Limite de batches por sessao Socket.IO. SDK envia 1 a cada 5s
    # (intervaloEnvioMs default), entao 720/h. Padrao 10000 cobre sessoes
    # de ~14h sem precisar reconectar. 0 ou negativo desabilita o limite.
    SESSION_REQUEST_LIMIT = int(os.environ.get("SESSION_REQUEST_LIMIT", "10000"))


class DevelopmentConfig(Config):
    """Configuracao local de desenvolvimento."""

    DEBUG = True


class ProductionConfig(Config):
    """Configuracao reservada para uso futuro em ambiente separado."""

    DEBUG = False


class TestingConfig(Config):
    """Configuracao para testes."""

    TESTING = True
    DEBUG = True
    TEMPORAL_REALTIME_INTERVAL = 1000
    TEMPORAL_REGULAR_INTERVAL = 3000


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}
