import { io, Socket } from 'socket.io-client';
import { HeatmapDados } from './HeatmapUtils.tsx';
import type { Ambiente } from './iniciarAnalytics.ts';
import {
  FilaAnalytics,
  criarStorageFila,
  emitirEventoDeadLetter,
  emitirEventoEnqueueFailed,
  emitirEventoPayloadRejected,
  BACKOFF_RETRY_MS,
  type ItemFila,
  type StorageFila,
} from './filaAnalytics.ts';
import { AuthClient, SDK_SCHEMA_VERSION, type BackpressureHint } from './authClient.ts';
import { userStore } from './identidade/userStore.ts';

interface ConfigSdk {
  websocketUrl: string;
  appId: string;
  ambiente: Ambiente;
  debug?: boolean;
  intervaloEnvioMs?: number;
  limiteFilaOffline?: number;
  storageFila?: StorageFila;
  publishableKey?: string;
  backendBaseUrl?: string; // URL HTTP do backend (default: derivada de websocketUrl)
}

const LOTE_DRENAGEM = 5;
const TIMEOUT_ACK_MS = 10_000;
const MAX_TENTATIVAS = BACKOFF_RETRY_MS.length;

const ANALYTICS_SESSION_STORAGE_KEY = 'analytics_sdk.session_id';
const SLOW_MULTIPLIER = 3;
const SLOW_DURATION_MS = 60_000;
const STOP_DURATION_MS = 120_000;
const SKEW_THRESHOLD_MS = 30_000;

interface AckSchema11 {
  schema_version: string;
  status: 'success' | 'error';
  id_registro?: string;
  server_seq?: number;
  server_time?: number;
  backpressure_hint?: BackpressureHint;
  code?: string;
  message?: string;
  fields?: string[];
  retriable?: boolean;
  duplicado?: boolean;
}

class WebSocketService {
  private socket: Socket | null = null;
  private isConnected: boolean = false;
  private serverUrl: string | null = null;
  private connectionAttempts: number = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private dataSendInterval: ReturnType<typeof setInterval> | null = null;

  private fila: FilaAnalytics | null = null;
  private emVoo: Set<string> = new Set();
  private tamanhoFilaCache: number = 0;
  private _deadLetter: Array<{ idRegistro: string | null; tentativas: number; ultimoErro?: string; ts: number }> = [];

  private realtimeIntervalBaseMs: number = 5000;
  private realtimeIntervalAtualMs: number = 5000;
  private appId: string | null = null;
  private ambiente: Ambiente | null = null;
  private debug: boolean = false;
  private configurado: boolean = false;

  private authClient: AuthClient | null = null;
  private analyticsSessionId: string | null = null;

  private serverTimeSkewMs: number = 0;
  private backpressureAtual: BackpressureHint = 'ok';
  private pausarAte: number = 0;
  private voltarAoNormalEm: number = 0;

  constructor() {
    if (typeof window !== 'undefined') {
      window.addEventListener('beforeunload', this._handleBeforeUnload);
    }
  }

  configurar(config: ConfigSdk): void {
    this.serverUrl = config.websocketUrl;
    this.appId = config.appId;
    this.ambiente = config.ambiente;
    this.debug = config.debug ?? false;
    this.realtimeIntervalBaseMs = config.intervaloEnvioMs ?? 5000;
    this.realtimeIntervalAtualMs = this.realtimeIntervalBaseMs;
    this.configurado = true;

    const storage = config.storageFila ?? criarStorageFila();
    const limite = config.limiteFilaOffline ?? 500;
    this.fila = new FilaAnalytics(storage, limite);

    this.analyticsSessionId = this._obterOuCriarSessionId();

    if (config.publishableKey) {
      const backendBase = config.backendBaseUrl ?? this._derivarBackendHttp(config.websocketUrl);
      this.authClient = new AuthClient({
        backendBaseUrl: backendBase,
        publishableKey: config.publishableKey,
        analyticsSessionId: this.analyticsSessionId,
        debug: this.debug,
        onUnsupportedSchema: ({ serverMin, cliente }) => {
          if (this.debug) {
            console.error(`[sdk] schema ${cliente} abaixo do minimo servidor ${serverMin}`);
          }
        },
      });
      void this._sincronizarPosAuth();
    }

    void this._atualizarTamanhoFila();
    this._initPeriodicDataSend();
  }

  private _derivarBackendHttp(wsUrl: string): string {
    // ws://, wss:// -> http://, https://; ja http(s) mantem
    return wsUrl.replace(/^wss:/, 'https:').replace(/^ws:/, 'http:');
  }

  private _obterOuCriarSessionId(): string {
    if (typeof sessionStorage !== 'undefined') {
      try {
        const existente = sessionStorage.getItem(ANALYTICS_SESSION_STORAGE_KEY);
        if (existente) return existente;
        const novo = crypto.randomUUID();
        sessionStorage.setItem(ANALYTICS_SESSION_STORAGE_KEY, novo);
        return novo;
      } catch {
        /* storage indisponivel */
      }
    }
    return crypto.randomUUID();
  }

  /** Apos obter sdk_jwt inicial, aplica resync e skew se houver. */
  private async _sincronizarPosAuth(): Promise<void> {
    if (!this.authClient) return;
    await this.authClient.obterToken();
    await this._aplicarResyncEInicializar();
  }

  private async _aplicarResyncEInicializar(): Promise<void> {
    if (!this.authClient || !this.fila) return;
    const lastAt = this.authClient.lastReceivedAt;
    if (lastAt) {
      const descartados = await this.fila.descartarAteTimestamp(lastAt);
      if (descartados.length && this.debug) {
        console.info(`[sdk] resync removeu ${descartados.length} itens ja recebidos`);
      }
    }
    await this._atualizarTamanhoFila();
  }

  private async _atualizarTamanhoFila(): Promise<void> {
    if (!this.fila) {
      this.tamanhoFilaCache = 0;
      return;
    }
    try {
      this.tamanhoFilaCache = await this.fila.tamanho();
    } catch {
      /* mantem cache anterior */
    }
  }

  private _initPeriodicDataSend(): void {
    if (this.dataSendInterval) clearInterval(this.dataSendInterval);
    this.dataSendInterval = setInterval(() => {
      void this._drenar();
    }, this.realtimeIntervalAtualMs);
  }

  private _handleBeforeUnload = (): void => {
    void this._drenar(true);
  };

  async connect(): Promise<boolean> {
    if (!this.configurado || !this.serverUrl) {
      if (this.debug) {
        console.warn('[WebSocketService] Chame iniciarAnalytics() antes de usar o SDK.');
      }
      return false;
    }

    if (this.socket && this.isConnected) return true;

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.connectionAttempts > 5) return false;
    this.connectionAttempts++;

    const token = this.authClient ? await this.authClient.obterToken() : null;
    const auth: Record<string, unknown> = {};
    if (token) auth.token = token;
    if (this.analyticsSessionId) auth.analytics_session_id = this.analyticsSessionId;

    return new Promise<boolean>((resolve) => {
      try {
        this.socket = io(this.serverUrl!, {
          // Path canonico SEM /api/. Backend escuta em /socket.io/. Subdominio
          // api.X proxia direto; apex dsplayground.com.br/api/socket.io/ tambem
          // funciona (nginx strippa /api/ no apex). Mudou em v0.3.0.
          path: '/socket.io/',
          transports: ['websocket', 'polling'],
          timeout: 20000,
          forceNew: false,
          reconnection: true,
          reconnectionAttempts: 5,
          reconnectionDelay: 1000,
          auth,
        });

        const connectTimeout = setTimeout(() => {
          if (!this.isConnected) resolve(false);
        }, 10000);

        this.socket.on('connect', () => {
          this.isConnected = true;
          this.connectionAttempts = 0;
          clearTimeout(connectTimeout);
          void this._drenar();
          resolve(true);
        });

        this.socket.on('connection_response', (resp: {
          last_received_id_registro?: string | null;
          last_received_at?: number | null;
          server_time?: number;
        }) => {
          this._registrarResyncDoConnect(resp);
        });

        this.socket.on('disconnect', (reason: string) => {
          this.isConnected = false;
          if (reason !== 'io client disconnect') {
            this.reconnectTimer = setTimeout(() => {
              void this.connect();
            }, 2000);
          }
        });

        this.socket.on('connect_error', () => {
          clearTimeout(connectTimeout);
          const backoffDelay = Math.min(2000 * Math.pow(2, this.connectionAttempts), 10000);
          this.reconnectTimer = setTimeout(() => {
            void this.connect();
          }, backoffDelay);
        });
      } catch {
        resolve(false);
      }
    });
  }

  private async _registrarResyncDoConnect(resp: {
    last_received_id_registro?: string | null;
    last_received_at?: number | null;
    server_time?: number;
  }): Promise<void> {
    if (resp.server_time) {
      const skew = resp.server_time - Date.now();
      if (Math.abs(skew) > SKEW_THRESHOLD_MS) {
        this.serverTimeSkewMs = skew;
        if (this.debug) console.info(`[sdk] skew corrigido: ${skew}ms`);
      } else {
        this.serverTimeSkewMs = 0;
      }
    }
    if (resp.last_received_at && this.fila) {
      const removidos = await this.fila.descartarAteTimestamp(resp.last_received_at);
      if (removidos.length && this.debug) {
        console.info(`[sdk] resync via connect removeu ${removidos.length} itens`);
      }
      await this._atualizarTamanhoFila();
    }
  }

  async sendAnalyticsData(heatmapDados: HeatmapDados): Promise<boolean> {
    if (!this.fila) return false;
    if (!(await this._enfileirarSeguro(heatmapDados))) return false;
    await this._atualizarTamanhoFila();
    return this._drenar();
  }

  async sendAnalyticsDataImmediate(heatmapDados: HeatmapDados, priority: boolean = false): Promise<boolean> {
    if (priority && this.configurado) {
      if (!this.socket || !this.isConnected) {
        const connected = await this.connect();
        if (!connected) return this.sendAnalyticsData(heatmapDados);
      }
      const ack = await this._emitAnalyticsData(heatmapDados);
      return ack?.status === 'success';
    }
    return this.sendAnalyticsData(heatmapDados);
  }

  /** Enfileira propagando falhas de storage como evento observavel + retorno false. */
  private async _enfileirarSeguro(heatmapDados: HeatmapDados): Promise<boolean> {
    if (!this.fila) return false;
    try {
      await this.fila.enfileirar({ ...heatmapDados });
      return true;
    } catch (erro) {
      const idRegistro = (heatmapDados as unknown as { id_registro?: string })?.id_registro ?? null;
      const reason = erro instanceof Error ? `${erro.name}: ${erro.message}` : String(erro);
      const storage = typeof indexedDB !== 'undefined'
        ? 'indexeddb'
        : typeof localStorage !== 'undefined'
          ? 'localstorage'
          : 'memoria';
      if (this.debug) {
        console.warn('[sdk] falha ao enfileirar analytics:', reason);
      }
      emitirEventoEnqueueFailed({ idRegistro, reason, storage });
      return false;
    }
  }

  private async _drenar(forceSynchronous: boolean = false): Promise<boolean> {
    if (!this.fila || !this.configurado) return false;

    // Backpressure: stop => para de drenar ate pausarAte expirar.
    const agora = Date.now();
    if (this.backpressureAtual === 'stop' && agora < this.pausarAte) {
      await this._atualizarTamanhoFila();
      return false;
    }

    const tamanho = await this.fila.tamanho();
    if (tamanho === 0) {
      this.tamanhoFilaCache = 0;
      return true;
    }

    if (!this.socket || !this.isConnected) {
      const connected = forceSynchronous ? await this._connectAndWait() : await this.connect();
      if (!connected) {
        await this._atualizarTamanhoFila();
        return false;
      }
    }

    const lote = await this.fila.proximoLote(LOTE_DRENAGEM, this.emVoo);
    let todosOk = true;

    for (const item of lote) {
      this.emVoo.add(item.id);
      try {
        const ack = await this._emitAnalyticsData(item.payload);
        if (ack && ack.status === 'success') {
          await this.fila.confirmar([item.id]);
          this._absorverBackpressureHint(ack.backpressure_hint ?? 'ok');
        } else if (ack && ack.status === 'error' && ack.retriable === false) {
          // Erro definitivo — drop e avisa consumidor.
          emitirEventoPayloadRejected({
            idRegistro: ack.id_registro ?? null,
            code: ack.code ?? 'UNKNOWN',
            fields: ack.fields ?? [],
          });
          await this.fila.confirmar([item.id]);
          this._absorverBackpressureHint(ack.backpressure_hint ?? 'ok');
        } else {
          // Timeout, erro retriable, disconnect — incrementa tentativa.
          const atualizado = await this.fila.incrementarTentativa(
            item.id,
            ack?.code ?? 'TIMEOUT',
          );
          if (atualizado && atualizado.tentativas >= MAX_TENTATIVAS) {
            const entrada = {
              idRegistro: (item.payload as unknown as { id_registro?: string })?.id_registro ?? null,
              tentativas: atualizado.tentativas,
              ultimoErro: atualizado.ultimoErro,
              ts: Date.now(),
            };
            this._deadLetter.push(entrada);
            emitirEventoDeadLetter(entrada);
            await this.fila.confirmar([item.id]);
          }
          todosOk = false;
          // Proximo ciclo obedece proximaTentativaApos — sem break precisa de guardas.
          break;
        }
      } finally {
        this.emVoo.delete(item.id);
      }
    }

    await this._atualizarTamanhoFila();
    return todosOk;
  }

  private _absorverBackpressureHint(hint: BackpressureHint): void {
    const agora = Date.now();
    if (hint === 'stop') {
      this.backpressureAtual = 'stop';
      this.pausarAte = agora + STOP_DURATION_MS;
      this._ajustarIntervalo(this.realtimeIntervalBaseMs * SLOW_MULTIPLIER);
    } else if (hint === 'slow') {
      this.backpressureAtual = 'slow';
      this.voltarAoNormalEm = agora + SLOW_DURATION_MS;
      this._ajustarIntervalo(this.realtimeIntervalBaseMs * SLOW_MULTIPLIER);
    } else {
      // hint=ok: se estavamos em slow/stop, consideramos normalizar.
      if (this.backpressureAtual !== 'ok') {
        if (this.backpressureAtual === 'stop' && agora >= this.pausarAte) {
          this.backpressureAtual = 'ok';
          this._ajustarIntervalo(this.realtimeIntervalBaseMs);
        } else if (this.backpressureAtual === 'slow' && agora >= this.voltarAoNormalEm) {
          this.backpressureAtual = 'ok';
          this._ajustarIntervalo(this.realtimeIntervalBaseMs);
        }
      }
    }
  }

  private _ajustarIntervalo(novoMs: number): void {
    if (novoMs === this.realtimeIntervalAtualMs) return;
    this.realtimeIntervalAtualMs = novoMs;
    this._initPeriodicDataSend();
    if (this.debug) console.info(`[sdk] intervalo ajustado para ${novoMs}ms`);
  }

  private _connectAndWait(): Promise<boolean> {
    return new Promise((resolve) => {
      void this.connect().then(resolve);
    });
  }

  private _emitAnalyticsData(heatmapDados: HeatmapDados): Promise<AckSchema11 | null> {
    return new Promise((resolve) => {
      if (!this.socket) {
        resolve(null);
        return;
      }

      // Schema 1.2 (v0.4): identidade opcional injetada do UserStore.
      // Campos so entram no envelope quando setados via identify/group —
      // omissao mantem forward-compat com backend velho (que ignora) e
      // evita mandar 'null' literal.
      const userId = userStore.getUserId();
      const groupId = userStore.getGroupId();

      // Aplica skew em timestamps se necessario.
      const payload = this._aplicarSkew({
        ...heatmapDados,
        app_id: this.appId,
        ambiente: this.ambiente,
        schema_version: SDK_SCHEMA_VERSION,
        ...(userId ? { user_id: userId } : {}),
        ...(groupId ? { group_id: groupId } : {}),
      } as unknown as Record<string, unknown>);

      const emitTimeout = setTimeout(() => resolve(null), TIMEOUT_ACK_MS);

      const onSuccess = (ack: AckSchema11) => {
        clearTimeout(emitTimeout);
        this.socket?.off('analytics_error', onError);
        resolve(ack);
      };

      const onError = (ack: AckSchema11) => {
        clearTimeout(emitTimeout);
        this.socket?.off('analytics_received', onSuccess);
        resolve(ack);
      };

      this.socket.once('analytics_received', onSuccess);
      this.socket.once('analytics_error', onError);

      this.socket.emit('analytics_data', payload);
    });
  }

  private _aplicarSkew(payload: Record<string, unknown>): Record<string, unknown> {
    if (this.serverTimeSkewMs === 0) return payload;
    const copia: Record<string, unknown> = { ...payload };
    if (typeof copia.timestamp_inicial === 'number') {
      copia.timestamp_inicial = copia.timestamp_inicial + this.serverTimeSkewMs;
    }
    if (typeof copia.timestamp_final === 'number') {
      copia.timestamp_final = copia.timestamp_final + this.serverTimeSkewMs;
    }
    return copia;
  }

  disconnect(): void {
    if (typeof window !== 'undefined') {
      window.removeEventListener('beforeunload', this._handleBeforeUnload);
    }

    if (this.dataSendInterval) {
      clearInterval(this.dataSendInterval);
      this.dataSendInterval = null;
    }

    void this._drenar(true).finally(() => {
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
      if (this.socket) {
        this.socket.disconnect();
        this.socket = null;
        this.isConnected = false;
      }
      this.authClient?.destruir();
    });
  }

  async limparFilaOffline(): Promise<void> {
    if (!this.fila) return;
    await this.fila.limpar();
    this.emVoo.clear();
    this.tamanhoFilaCache = 0;
  }

  /**
   * Retorna uma copia snapshot dos itens que excederam MAX_TENTATIVAS e foram
   * descartados da fila (dead-letter). Util para monitoramento ou relay manual.
   * Chame `limparDeadLetter()` para esvaziar apos inspecionar.
   */
  getDeadLetter(): ReadonlyArray<{ idRegistro: string | null; tentativas: number; ultimoErro?: string; ts: number }> {
    return [...this._deadLetter];
  }

  limparDeadLetter(): void {
    this._deadLetter = [];
  }

  async tamanhoFilaOffline(): Promise<number> {
    if (!this.fila) return 0;
    return this.fila.tamanho();
  }

  getConnectionStatus(): {
    isConnected: boolean;
    socketId: string | null;
    attempts: number;
    pendingData: number;
    backpressure: BackpressureHint;
    intervalMs: number;
    skewMs: number;
  } {
    return {
      isConnected: this.isConnected,
      socketId: this.socket?.id || null,
      attempts: this.connectionAttempts,
      pendingData: this.tamanhoFilaCache,
      backpressure: this.backpressureAtual,
      intervalMs: this.realtimeIntervalAtualMs,
      skewMs: this.serverTimeSkewMs,
    };
  }

  setRealtimeInterval(intervalMs: number): void {
    this.realtimeIntervalBaseMs = intervalMs;
    this.realtimeIntervalAtualMs = intervalMs;
    if (this.configurado) this._initPeriodicDataSend();
  }
}

export default new WebSocketService();
