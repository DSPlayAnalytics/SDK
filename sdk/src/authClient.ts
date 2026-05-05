/**
 * Cliente de autenticacao do SDK: troca publishable_key por sdk_jwt de 5 min
 * e mantem o token vivo via refresh assincrono antes da expiracao.
 *
 * Integra com o endpoint POST /auth/sdk-token do backend (ver
 * docs/plano-garantias-sdk-backend.md).
 */

export const SDK_SCHEMA_VERSION = '1.2';
const REFRESH_MARGIN_SECONDS = 60; // renova 60s antes de expirar

export type BackpressureHint = 'ok' | 'slow' | 'stop';

export interface SdkTokenResposta {
  token: string;
  expiresIn: number;
  serverTime: number;
  serverSchemaVersion: string;
  minClientSchema: string;
  lastReceivedIdRegistro: string | null;
  lastReceivedAt: number | null;
}

export interface AuthClientConfig {
  backendBaseUrl: string;      // ex.: https://api.dsplayground
  publishableKey: string;
  analyticsSessionId: string;  // id logico de sessao (nao sid do socket)
  debug?: boolean;
  onUnsupportedSchema?: (info: { serverMin: string; cliente: string }) => void;
}

export class AuthClient {
  private config: AuthClientConfig;
  private tokenAtual: string | null = null;
  private tokenExp: number = 0;
  private ultimoRecebidoId: string | null = null;
  private ultimoRecebidoAt: number | null = null;
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;
  private refreshEmAndamento: Promise<SdkTokenResposta | null> | null = null;

  constructor(config: AuthClientConfig) {
    this.config = config;
  }

  get lastReceivedIdRegistro(): string | null {
    return this.ultimoRecebidoId;
  }

  get lastReceivedAt(): number | null {
    return this.ultimoRecebidoAt;
  }

  /** Retorna token valido (renovando se necessario). `null` em caso de falha. */
  async obterToken(): Promise<string | null> {
    const agoraSeg = Math.floor(Date.now() / 1000);
    if (this.tokenAtual && agoraSeg < this.tokenExp - REFRESH_MARGIN_SECONDS) {
      return this.tokenAtual;
    }
    const resposta = await this._solicitar();
    return resposta?.token ?? null;
  }

  /** Força solicitação de novo token. Seguro para chamar várias vezes em paralelo. */
  async _solicitar(): Promise<SdkTokenResposta | null> {
    if (this.refreshEmAndamento) return this.refreshEmAndamento;

    this.refreshEmAndamento = (async () => {
      try {
        const url = `${this.config.backendBaseUrl.replace(/\/$/, '')}/auth/sdk-token`;
        const resp = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-SDK-Schema-Version': SDK_SCHEMA_VERSION,
          },
          body: JSON.stringify({
            publishable_key: this.config.publishableKey,
            analytics_session_id: this.config.analyticsSessionId,
          }),
          credentials: 'omit',
        });

        if (resp.status === 426) {
          const body = await resp.json().catch(() => ({}));
          if (this.config.debug) {
            console.error('[sdk] schema incompativel:', body);
          }
          this.config.onUnsupportedSchema?.({
            serverMin: String(body?.message ?? 'desconhecido'),
            cliente: SDK_SCHEMA_VERSION,
          });
          return null;
        }

        if (!resp.ok) {
          if (this.config.debug) {
            const body = await resp.text().catch(() => '');
            console.warn(`[sdk] falha ao obter sdk_jwt (${resp.status}):`, body);
          }
          return null;
        }

        const json = await resp.json();
        const resposta: SdkTokenResposta = {
          token: json.token,
          expiresIn: json.expires_in,
          serverTime: json.server_time,
          serverSchemaVersion: json.server_schema_version,
          minClientSchema: json.min_client_schema,
          lastReceivedIdRegistro: json.last_received_id_registro ?? null,
          lastReceivedAt: json.last_received_at ?? null,
        };

        this.tokenAtual = resposta.token;
        this.tokenExp = Math.floor(Date.now() / 1000) + resposta.expiresIn;
        this.ultimoRecebidoId = resposta.lastReceivedIdRegistro;
        this.ultimoRecebidoAt = resposta.lastReceivedAt;

        this._agendarRefresh(resposta.expiresIn);
        return resposta;
      } catch (erro) {
        if (this.config.debug) {
          console.warn('[sdk] erro na solicitacao de sdk_jwt:', erro);
        }
        return null;
      } finally {
        this.refreshEmAndamento = null;
      }
    })();

    return this.refreshEmAndamento;
  }

  private _agendarRefresh(expiresIn: number): void {
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
    const atrasoMs = Math.max(5_000, (expiresIn - REFRESH_MARGIN_SECONDS) * 1000);
    this.refreshTimer = setTimeout(() => {
      void this._solicitar();
    }, atrasoMs);
  }

  destruir(): void {
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
    this.tokenAtual = null;
    this.tokenExp = 0;
  }
}
