import { useEffect, useRef, useCallback } from 'react';
import { HeatmapUtils, WebSocketService } from '@danpqdan/dsplayground-analytics-sdk';
import { DEBUG_ENABLED } from '../config.js';

type UseHeatmapOptions = {
    debug?: boolean;
    realtimeInterval?: number; // ms entre emissoes de delta
};

export const useHeatmap = (
    paginaTipo: string,
    hoverSelector: string | null = null,
    options: UseHeatmapOptions = {}
) => {
    const heatmapRef = useRef<HeatmapUtils | null>(null);
    const isActiveRef = useRef<boolean>(false);

    const defaultOptions: UseHeatmapOptions = {
        debug: DEBUG_ENABLED,
        realtimeInterval: 5000,
    };

    const mergedOptions = { ...defaultOptions, ...options };

    useEffect(() => {
        const connectWebSocket = async () => {
            try {
                await WebSocketService.connect();
                if (mergedOptions.realtimeInterval) {
                    WebSocketService.setRealtimeInterval(mergedOptions.realtimeInterval);
                }

                if (mergedOptions.debug) {
                    console.log('[useHeatmap] WebSocket conectado para pagina', paginaTipo);
                }
            } catch (error) {
                if (mergedOptions.debug) {
                    console.error('[useHeatmap] Erro ao conectar WebSocket:', error);
                }
            }
        };

        connectWebSocket();
    }, [paginaTipo, mergedOptions.debug, mergedOptions.realtimeInterval]);

    useEffect(() => {
        const heatmap = new HeatmapUtils(document.body, hoverSelector, paginaTipo);
        heatmapRef.current = heatmap;

        heatmap.configurarColecaoTempoReal(
            (dados) => {
                WebSocketService.sendAnalyticsDataImmediate(dados, false);

                if (mergedOptions.debug) {
                    console.log(`[useHeatmap] Delta enviado para ${paginaTipo}`, {
                        timestamp: new Date().toISOString(),
                        tempoPermanciaSegundos: heatmap.getTempoPermanciaSegundos(),
                    });
                }
            },
            mergedOptions.realtimeInterval,
        );

        heatmap.iniciarColecaoTempoReal();
        heatmap.iniciar();
        isActiveRef.current = true;

        return () => {
            if (isActiveRef.current && heatmapRef.current) {
                heatmapRef.current.parar(); // emite residuo final via callback
                isActiveRef.current = false;
            }
        };
    }, [paginaTipo, hoverSelector, mergedOptions.realtimeInterval, mergedOptions.debug]);

    const enviarDados = useCallback(() => {
        if (heatmapRef.current) {
            heatmapRef.current.emitirDeltaAgora();
            return true;
        }
        return false;
    }, []);

    const pararEEnviarDados = useCallback(() => {
        if (isActiveRef.current && heatmapRef.current) {
            heatmapRef.current.parar();
            isActiveRef.current = false;
            return true;
        }
        return false;
    }, []);

    const reiniciarRastreamento = useCallback(() => {
        if (!isActiveRef.current && heatmapRef.current) {
            heatmapRef.current.iniciar();
            isActiveRef.current = true;
            return true;
        }
        return false;
    }, []);

    const getWebSocketStatus = useCallback(() => {
        return WebSocketService.getConnectionStatus();
    }, []);

    const getTempoPermancia = useCallback(() => {
        if (heatmapRef.current) {
            return heatmapRef.current.getTempoPermanciaSegundos();
        }
        return 0;
    }, []);

    const setRealtimeInterval = useCallback((intervalMs: number) => {
        WebSocketService.setRealtimeInterval(intervalMs);

        if (mergedOptions.debug) {
            console.log(`[useHeatmap] Intervalo de coleta alterado para ${intervalMs}ms`);
        }
    }, [mergedOptions.debug]);

    return {
        enviarDados,
        pararEEnviarDados,
        reiniciarRastreamento,
        getWebSocketStatus,
        getTempoPermancia,
        setRealtimeInterval,
        isActive: isActiveRef.current,
    };
};
