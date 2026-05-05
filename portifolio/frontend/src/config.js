/**
 * Configurações centralizadas da aplicação
 * Acessa variáveis de ambiente através do import.meta.env
 */

// Ambiente
export const IS_DEV = import.meta.env.MODE !== 'production';
export const IS_PROD = import.meta.env.MODE === 'production';
export const NODE_ENV = import.meta.env.MODE;

// URLs
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';
export const WEBSOCKET_URL = import.meta.env.VITE_WEBSOCKET_URL || 'http://localhost:5000';

// Flags
export const DEBUG_ENABLED = import.meta.env.VITE_DEBUG === 'true' || IS_DEV; // Habilitar debug em desenvolvimento

// SDK auth: quando presente, o cliente troca pela JWT no /sdk-token e envia
// eventos vinculados ao site_id correspondente (bucket dedicado). Quando vazio,
// o SDK opera sem auth e os eventos caem no bucket default em dev. Em prod,
// SDK_AUTH_REQUIRED no backend forca presence dessa key.
export const PUBLISHABLE_KEY = import.meta.env.VITE_PUBLISHABLE_KEY || '';

export default {
    IS_DEV,
    IS_PROD,
    NODE_ENV,
    API_URL,
    WEBSOCKET_URL,
    DEBUG_ENABLED,
    PUBLISHABLE_KEY,
};