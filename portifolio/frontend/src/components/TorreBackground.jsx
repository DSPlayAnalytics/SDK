import { useEffect, useRef } from 'react';
import torre from '../assets/videos/torre_eifield.mp4';

export default function TorreBackground({ onEnded }) {
  const ref = useRef(null);

  useEffect(() => {
    const v = ref.current;
    if (!v) return;

    const handlePlay = () => {
      // notify that torre started (some callers already dispatch this, but keep for robustness)
      window.dispatchEvent(new CustomEvent('torre:started'));
    };

    v.addEventListener('play', handlePlay);

    const tryPlay = async () => {
      try {
        v.muted = true; // ✅ SEMPRE MUDO
        v.loop = true;  // ✅ LOOP INFINITO
        v.currentTime = 0;
        await v.play();
      } catch (error) {
        console.log('Erro ao reproduzir vídeo Torre:', error);
        // ignore final failure
      }
    };

    tryPlay();

    return () => {
      v.removeEventListener('play', handlePlay);
    };
  }, [onEnded]);

  // ✅ DETECTAR LARGURA DA TELA PARA AJUSTAR POSIÇÃO
  const getVideoStyle = () => {
    const baseStyle = {
      width: '100%',
      // 100dvh = dynamic viewport height; considera a barra de URL retratil do iOS Safari
      height: '100dvh',
      objectFit: 'cover',
      display: 'block'
    };

    // Verificar se é mobile < 380px
    if (window.innerWidth < 380) {
      return {
        ...baseStyle,
        objectPosition: '75% center', // Move o foco do vídeo para a direita
        width: '100%' // Compensa o translate aumentando a largura
      };
    }

    return baseStyle;
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      width: '100%',
      height: '100dvh',
      zIndex: 20000,
      pointerEvents: 'none',
      overflow: 'hidden' // ✅ EVITA SCROLL HORIZONTAL
    }}>
      <video
        ref={ref}
        src={torre}
        muted
        loop
        playsInline
        style={getVideoStyle()}
      />
    </div>
  );
}
