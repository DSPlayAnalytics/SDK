import React from 'react';
import { IS_DEV } from '../config.js';

export default function DebugStatusBar({ webSocketStatus, onEnviarDados }) {
  if (!IS_DEV) return null;
  
  return (
    <>
      {/* Status do WebSocket */}
      <div style={{
        position: 'absolute',
        top: '10px',
        right: '10px',
        background: webSocketStatus.isConnected ? 'rgba(0, 128, 0, 0.7)' : 'rgba(255, 0, 0, 0.7)',
        color: 'white',
        padding: '5px 10px',
        borderRadius: '4px',
        fontSize: '12px',
        zIndex: 9999
      }}>
        {webSocketStatus.isConnected ? '🟢' : '🔴'} WebSocket
        {webSocketStatus.pendingData > 0 && ` (${webSocketStatus.pendingData} pendentes)`}
      </div>
      
      {/* Botão de teste para envio de dados */}
      <button 
        onClick={onEnviarDados}
        style={{
          position: 'absolute',
          bottom: '10px',
          right: '10px',
          background: 'rgba(0, 0, 255, 0.7)',
          color: 'white',
          border: 'none',
          borderRadius: '4px',
          padding: '5px 10px',
          fontSize: '12px',
          cursor: 'pointer',
          zIndex: 9999
        }}
      >
        📊 Testar Envio
      </button>
    </>
  );
}