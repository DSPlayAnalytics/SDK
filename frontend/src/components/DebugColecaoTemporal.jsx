import { useState, useEffect } from 'react';
import { useHeatmap } from '../hooks/useHeatmap.tsx';
import { WebSocketService } from '@danpqdan/dsplayground-analytics-sdk';
import '../styles/debug.css';

/**
 * Componente de debug para monitorar a coleta temporal em tempo real
 * Adicione este componente a qualquer página para visualizar os dados sendo coletados
 */
export default function DebugColecaoTemporal({ paginaTipo = '/' }) {
    const [debugData, setDebugData] = useState({
        tempoPermancia: 0,
        websocketStatus: { isConnected: false, pendingData: 0 },
        ultimoEnvio: null,
        totalEnvios: 0
    });

    const [intervaloCustomizado, setIntervaloCustomizado] = useState(5000);
    const [isVisible, setIsVisible] = useState(true);

    const { 
        getTempoPermancia, 
        setRealtimeInterval, 
        getWebSocketStatus, 
        enviarDados 
    } = useHeatmap(paginaTipo, null, {
        realtimeCollection: true,
        realtimeInterval: intervaloCustomizado,
        debug: true
    });

    // Atualizar dados de debug a cada segundo
    useEffect(() => {
        const timer = setInterval(() => {
            setDebugData(prev => ({
                ...prev,
                tempoPermancia: getTempoPermancia(),
                websocketStatus: getWebSocketStatus()
            }));
        }, 1000);

        return () => clearInterval(timer);
    }, [getTempoPermancia, getWebSocketStatus]);

    // Monitorar envios via interceptação do WebSocket
    useEffect(() => {
        let envioCount = 0;
        const originalSend = WebSocketService.sendAnalyticsDataImmediate;
        
        WebSocketService.sendAnalyticsDataImmediate = function(...args) {
            envioCount++;
            setDebugData(prev => ({
                ...prev,
                ultimoEnvio: new Date().toLocaleTimeString(),
                totalEnvios: envioCount
            }));
            return originalSend.apply(this, args);
        };

        return () => {
            WebSocketService.sendAnalyticsDataImmediate = originalSend;
        };
    }, []);

    const handleIntervaloChange = (novoIntervalo) => {
        setIntervaloCustomizado(novoIntervalo);
        setRealtimeInterval(novoIntervalo);
    };

    const handleEnvioManual = () => {
        enviarDados();
    };

    const toggleVisibility = () => {
        setIsVisible(!isVisible);
    };

    if (!isVisible) {
        return (
            <button 
                onClick={toggleVisibility}
                style={{
                    position: 'fixed',
                    top: '10px',
                    right: '10px',
                    zIndex: 9999,
                    background: '#007bff',
                    color: 'white',
                    border: 'none',
                    borderRadius: '5px',
                    padding: '5px 10px',
                    cursor: 'pointer'
                }}
            >
                📊 Debug
            </button>
        );
    }

    return (
        <div className="debug-colecao-temporal">
            <div className="debug-header">
                <h3>🔍 Debug - Coleta Temporal ({paginaTipo})</h3>
                <button onClick={toggleVisibility} className="debug-close">×</button>
            </div>

            <div className="debug-content">
                <div className="debug-section">
                    <h4>⏱️ Tempo de Permanência</h4>
                    <div className="debug-value">
                        {debugData.tempoPermancia} segundos
                        <div className="debug-progress">
                            <div 
                                className="debug-progress-bar"
                                style={{ 
                                    width: `${(debugData.tempoPermancia % 60) * (100/60)}%` 
                                }}
                            />
                        </div>
                    </div>
                </div>

                <div className="debug-section">
                    <h4>🔌 WebSocket Status</h4>
                    <div className="debug-status">
                        <span className={`debug-indicator ${debugData.websocketStatus.isConnected ? 'connected' : 'disconnected'}`}>
                            {debugData.websocketStatus.isConnected ? '🟢 Conectado' : '🔴 Desconectado'}
                        </span>
                        <div>Dados pendentes: {debugData.websocketStatus.pendingData}</div>
                    </div>
                </div>

                <div className="debug-section">
                    <h4>📤 Envios</h4>
                    <div className="debug-envios">
                        <div>Total: {debugData.totalEnvios}</div>
                        <div>Último: {debugData.ultimoEnvio || 'Nenhum'}</div>
                        <button onClick={handleEnvioManual} className="debug-button">
                            Enviar Agora
                        </button>
                    </div>
                </div>

                <div className="debug-section">
                    <h4>⚙️ Configurações</h4>
                    <div className="debug-config">
                        <label>
                            Intervalo (ms):
                            <select 
                                value={intervaloCustomizado} 
                                onChange={(e) => handleIntervaloChange(Number(e.target.value))}
                                className="debug-select"
                            >
                                <option value={2000}>2 segundos</option>
                                <option value={3000}>3 segundos</option>
                                <option value={5000}>5 segundos</option>
                                <option value={10000}>10 segundos</option>
                                <option value={15000}>15 segundos</option>
                            </select>
                        </label>
                    </div>
                </div>

                <div className="debug-section">
                    <h4>📋 Logs</h4>
                    <div className="debug-logs">
                        <small>Abra o DevTools Console para ver logs detalhados</small>
                    </div>
                </div>
            </div>
        </div>
    );
}
