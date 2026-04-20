import { io, Socket } from 'socket.io-client';
import { HeatmapDados } from './HeatmapUtils.tsx';
import type { Ambiente } from './iniciarAnalytics.ts';
import { FilaAnalytics, criarStorageFila, type StorageFila } from './filaAnalytics.ts';

interface ConfigSdk {
    websocketUrl: string;
    appId: string;
    ambiente: Ambiente;
    debug?: boolean;
    intervaloEnvioMs?: number;
    limiteFilaOffline?: number;
    storageFila?: StorageFila; // override para testes
}

const LOTE_DRENAGEM = 5;

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

    private realtimeIntervalMs: number = 5000;
    private appId: string | null = null;
    private ambiente: Ambiente | null = null;
    private debug: boolean = false;
    private configurado: boolean = false;

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
        this.realtimeIntervalMs = config.intervaloEnvioMs ?? 5000;
        this.configurado = true;

        const storage = config.storageFila ?? criarStorageFila();
        const limite = config.limiteFilaOffline ?? 500;
        this.fila = new FilaAnalytics(storage, limite);

        this._atualizarTamanhoFila();
        this._initPeriodicDataSend();
    }

    private async _atualizarTamanhoFila(): Promise<void> {
        if (!this.fila) {
            this.tamanhoFilaCache = 0;
            return;
        }
        try {
            this.tamanhoFilaCache = await this.fila.tamanho();
        } catch {
            // storage indisponivel — mantem cache anterior
        }
    }

    private _initPeriodicDataSend(): void {
        if (this.dataSendInterval) {
            clearInterval(this.dataSendInterval);
        }
        this.dataSendInterval = setInterval(() => {
            this._drenar();
        }, this.realtimeIntervalMs);
    }

    private _handleBeforeUnload = (): void => {
        this._drenar(true);
    };

    connect(): Promise<boolean> {
        return new Promise((resolve) => {
            if (!this.configurado || !this.serverUrl) {
                if (this.debug) {
                    console.warn('[WebSocketService] Chame iniciarAnalytics() antes de usar o SDK.');
                }
                resolve(false);
                return;
            }

            if (this.socket && this.isConnected) {
                resolve(true);
                return;
            }

            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
                this.reconnectTimer = null;
            }

            if (this.connectionAttempts > 5) {
                resolve(false);
                return;
            }

            this.connectionAttempts++;

            try {
                this.socket = io(this.serverUrl, {
                    transports: ['websocket', 'polling'],
                    timeout: 20000,
                    forceNew: false,
                    reconnection: true,
                    reconnectionAttempts: 5,
                    reconnectionDelay: 1000,
                });

                const connectTimeout = setTimeout(() => {
                    if (!this.isConnected) resolve(false);
                }, 10000);

                this.socket.on('connect', () => {
                    this.isConnected = true;
                    this.connectionAttempts = 0;
                    clearTimeout(connectTimeout);
                    this._drenar();
                    resolve(true);
                });

                this.socket.on('disconnect', (reason: string) => {
                    this.isConnected = false;
                    if (reason !== 'io client disconnect') {
                        this.reconnectTimer = setTimeout(() => {
                            this.connect();
                        }, 2000);
                    }
                });

                this.socket.on('connect_error', () => {
                    clearTimeout(connectTimeout);
                    const backoffDelay = Math.min(2000 * Math.pow(2, this.connectionAttempts), 10000);
                    this.reconnectTimer = setTimeout(() => {
                        this.connect();
                    }, backoffDelay);
                });

                this.socket.on('analytics_received', () => {});
                this.socket.on('analytics_error', () => {});
                this.socket.on('connection_response', () => {});
            } catch {
                resolve(false);
            }
        });
    }

    async sendAnalyticsData(heatmapDados: HeatmapDados): Promise<boolean> {
        if (!this.fila) return false;
        await this.fila.enfileirar({ ...heatmapDados });
        await this._atualizarTamanhoFila();
        return this._drenar();
    }

    async sendAnalyticsDataImmediate(heatmapDados: HeatmapDados, priority: boolean = false): Promise<boolean> {
        if (priority && this.configurado) {
            if (!this.socket || !this.isConnected) {
                const connected = await this.connect();
                if (!connected) return this.sendAnalyticsData(heatmapDados);
            }
            return this._emitAnalyticsData(heatmapDados);
        }
        return this.sendAnalyticsData(heatmapDados);
    }

    private async _drenar(forceSynchronous: boolean = false): Promise<boolean> {
        if (!this.fila || !this.configurado) return false;

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

        const lote = await this.fila.proximoLote(LOTE_DRENAGEM);
        let todosOk = true;

        for (const item of lote) {
            if (this.emVoo.has(item.id)) continue;
            this.emVoo.add(item.id);
            try {
                const ok = await this._emitAnalyticsData(item.payload);
                if (ok) {
                    await this.fila.confirmar([item.id]);
                } else {
                    todosOk = false;
                    break;
                }
            } finally {
                this.emVoo.delete(item.id);
            }
        }

        await this._atualizarTamanhoFila();
        return todosOk;
    }

    private _connectAndWait(): Promise<boolean> {
        return new Promise((resolve) => {
            this.connect().then(resolve);
        });
    }

    private _emitAnalyticsData(heatmapDados: HeatmapDados): Promise<boolean> {
        return new Promise((resolve) => {
            if (!this.socket) {
                resolve(false);
                return;
            }

            const payload: Record<string, unknown> = {
                ...heatmapDados,
                app_id: this.appId,
                ambiente: this.ambiente,
            };

            const emitTimeout = setTimeout(() => resolve(false), 5000);

            const onSuccess = () => {
                clearTimeout(emitTimeout);
                this.socket?.off('analytics_error', onError);
                resolve(true);
            };

            const onError = () => {
                clearTimeout(emitTimeout);
                this.socket?.off('analytics_received', onSuccess);
                resolve(false);
            };

            this.socket.once('analytics_received', onSuccess);
            this.socket.once('analytics_error', onError);

            this.socket.emit('analytics_data', payload);
        });
    }

    disconnect(): void {
        if (typeof window !== 'undefined') {
            window.removeEventListener('beforeunload', this._handleBeforeUnload);
        }

        if (this.dataSendInterval) {
            clearInterval(this.dataSendInterval);
            this.dataSendInterval = null;
        }

        this._drenar(true).finally(() => {
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
                this.reconnectTimer = null;
            }
            if (this.socket) {
                this.socket.disconnect();
                this.socket = null;
                this.isConnected = false;
            }
        });
    }

    /**
     * Apaga a fila offline. Exposto para quando o consumidor revoga consentimento
     * (LGPD) e precisa garantir que nada persistido sobre armazenamento local sera
     * enviado mais tarde.
     */
    async limparFilaOffline(): Promise<void> {
        if (!this.fila) return;
        await this.fila.limpar();
        this.emVoo.clear();
        this.tamanhoFilaCache = 0;
    }

    async tamanhoFilaOffline(): Promise<number> {
        if (!this.fila) return 0;
        return this.fila.tamanho();
    }

    getConnectionStatus(): { isConnected: boolean; socketId: string | null; attempts: number; pendingData: number } {
        return {
            isConnected: this.isConnected,
            socketId: this.socket?.id || null,
            attempts: this.connectionAttempts,
            pendingData: this.tamanhoFilaCache,
        };
    }

    setRealtimeInterval(intervalMs: number): void {
        this.realtimeIntervalMs = intervalMs;
        if (this.configurado) {
            this._initPeriodicDataSend();
        }
    }
}

export default new WebSocketService();
