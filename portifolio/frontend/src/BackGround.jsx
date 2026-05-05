import { useEffect, useRef, useState } from "react";
import rotacao from './assets/videos/earth_light.mp4';
import entrada from './assets/videos/entrada.mp4';
import TorreBackground from './components/TorreBackground';

export default function BackGround() {
    const videoRef = useRef(null);
    const entradaRef = useRef(null);
    const [playingEntrada, setPlayingEntrada] = useState(false);
    const [showBlackFrame, setShowBlackFrame] = useState(false);
    const [blackFadeOut, setBlackFadeOut] = useState(false);
    const [showTorre, setShowTorre] = useState(false);
    const [blackTimeout, setBlackTimeout] = useState(null);

    useEffect(() => {
        const video = videoRef.current;
        if (!video) return;

        const onLoadedMetadata = () => {
            video.muted = true;
            video.play().catch(() => { /* ignore autoplay errors */ });
        };

        video.addEventListener('loadedmetadata', onLoadedMetadata);

        return () => {
            video.removeEventListener('loadedmetadata', onLoadedMetadata);
        };
    }, []);

    useEffect(() => {
        return () => {
            if (blackTimeout) {
                clearTimeout(blackTimeout);
            }
        };
    }, [blackTimeout]);

    const handleStartProject = async () => {
        const bg = videoRef.current;
        const ent = entradaRef.current;
        if (!ent) return;
        try { bg.pause(); } catch { /* ignore */ }
        setPlayingEntrada(true);
        try { ent.currentTime = 0; } catch { /* ignore */ }
        ent.muted = true; // ✅ VÍDEO DE ENTRADA TAMBÉM MUDO
        try { await ent.play(); } catch { /* ignore */ }

        const onEnded = () => {
            setPlayingEntrada(false);
            setShowBlackFrame(true);
            const t = setTimeout(() => {
                setShowTorre(true);
                // notify other parts that Torre video is starting
                window.dispatchEvent(new CustomEvent('torre:started'));
                setBlackFadeOut(true);
                try { bg.pause(); } catch { /* ignore */ }
            }, 2000);

            setBlackTimeout(t);
            window.dispatchEvent(new CustomEvent('entrada:ended'));
            ent.removeEventListener('ended', onEnded);
        };

        ent.addEventListener('ended', onEnded);
    };

    var styleContent = {
        width: '100%',
        height: '50px',
        objectFit: 'cover',
        position: 'fixed',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        top: '10%',
        left: 0,
        zIndex: 2,
        transformOrigin: 'center center'
    }

    var styleTitle = {
        backgroundColor: 'rgba(0, 0, 0, 0.5)',
        cursor: 'pointer',
        color: 'white',
        textAlign: 'center',
        lineHeight: '50px',
        fontSize: '24px',
        fontWeight: 'bold',
        border: '1px solid white',
        borderRadius: '8px',
        padding: '12px 36px',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center'
    }

    const overlayStyle = {
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        // 100dvh = dynamic viewport height: considera a barra de URL do iOS Safari
        height: '100dvh',
        zIndex: 9999,
        display: playingEntrada ? 'flex' : 'none',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.2)'
    };

    return (
        <div className="background">
            <div className="content" style={styleContent}>
                <button className="title" id="iniciar-projeto" style={styleTitle} onClick={handleStartProject}>Iniciar Projeto</button>
            </div>
            <video
                ref={videoRef}
                src={rotacao}
                className="background-video"
                muted // ✅ SEMPRE MUDO
                playsInline
                loop
                style={{
                    width: '100%',
                    height: '100dvh',
                    objectFit: 'cover',
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    zIndex: -1,
                    transformOrigin: 'center center'
                }}
            />
            <div style={overlayStyle} aria-hidden={!playingEntrada}>
                <video
                    ref={entradaRef}
                    src={entrada}
                    className="entrada-video"
                    muted // ✅ SEMPRE MUDO
                    playsInline
                    style={{
                        width: '100%',
                        height: '100dvh',
                        objectFit: 'cover'
                    }}
                />
            </div>
            {showBlackFrame && (
                <div
                    style={{
                        position: 'fixed',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: '100dvh',
                        backgroundColor: 'black',
                        zIndex: 10001,
                        opacity: blackFadeOut ? 0 : 1,
                        transition: 'opacity 1s ease'
                    }}
                />
            )}

            {showTorre && (
                <TorreBackground onEnded={() => {
                    // Como o vídeo agora é infinito, este callback pode não ser mais necessário
                    // Mantido para compatibilidade, mas nunca será chamado
                    window.dispatchEvent(new CustomEvent('torre:ended'));
                }} />
            )}
        </div>
    );
}