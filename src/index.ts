export {
  HeatmapDados,
  HeatmapUtils,
  type HeatmapDados as HeatmapDadosTipo,
  type MapaPaginasDados,
  type PaginaDados,
  type EventoNormalizado,
  type TipoEvento,
  type MarcoScroll,
  type MotivoSaida,
  type NomeWebVital,
  type RatingWebVital,
} from './HeatmapUtils.tsx';

export { default as WebSocketService } from './WebSocketService.tsx';

export { iniciarAnalytics, type AnalyticsConfig, type Ambiente } from './iniciarAnalytics.ts';

export { enviarEvento } from './eventosCustomizados.ts';

export { trackPurchase, trackSignup, trackConversion } from './comercial.ts';

export { identify, group, reset } from './identify.ts';
export { UserStore, criarUserStoreMemoria, userStore } from './identidade/userStore.ts';

export {
  FilaAnalytics,
  StorageMemoria,
  StorageLocalStorage,
  StorageIndexedDB,
  criarStorageFila,
  type StorageFila,
  type ItemFila,
} from './filaAnalytics.ts';
