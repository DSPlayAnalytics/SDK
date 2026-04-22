import WebSocketService from './WebSocketService.tsx';
import { iniciarWebVitals } from './webVitals.ts';

export type Ambiente = 'development' | 'test' | 'staging' | 'production';

export interface AnalyticsConfig {
  websocketUrl: string;
  appId: string;
  ambiente: Ambiente;
  debug?: boolean;
  intervaloEnvioMs?: number;
  /** Habilita coleta de Web Vitals (LCP/CLS/INP) via lib web-vitals. Default: true. */
  coletarPerformance?: boolean;
  /** Maximo de pontos de mouse_move por segundo. Default: 5. */
  taxaAmostragemMouseMove?: number;
  /** publishable_key emitida pelo backend (ver docs/plano-clientes-ambientes.md).
   *  Opcional durante migracao; obrigatoria quando SDK_AUTH_REQUIRED=true no backend. */
  publishableKey?: string;
  /** Base URL HTTP do backend (default: derivada de websocketUrl). Usado para chamar /auth/sdk-token. */
  backendBaseUrl?: string;
}

/**
 * Inicializa o SDK de analytics. Deve ser chamado uma unica vez antes de
 * qualquer uso de `WebSocketService`, `HeatmapUtils` ou `enviarEvento`.
 */
export function iniciarAnalytics(config: AnalyticsConfig): void {
  if (!config || !config.websocketUrl || !config.appId || !config.ambiente) {
    throw new Error('[iniciarAnalytics] websocketUrl, appId e ambiente sao obrigatorios');
  }

  WebSocketService.configurar(config);
  void WebSocketService.connect();

  const coletarPerformance = config.coletarPerformance ?? true;
  if (coletarPerformance && typeof window !== 'undefined') {
    iniciarWebVitals();
  }
}
