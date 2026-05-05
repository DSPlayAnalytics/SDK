import { useEffect, useRef, useState, useCallback, useLayoutEffect } from 'react';

import ClasseAbout from '../classe/ClasseAbout';
import ClasseHome from '../classe/ClasseHome';
import ClasseProjects from '../classe/ClasseProjects';
import '../styles/cards.css';

// Horizontal carousel using translateX; slides have no visible scroll (overflow: hidden)
export default function SlidesCarousel({ slides }) {
    const [index, setIndex] = useState(0);
    const [cardNodesVersion, setCardNodesVersion] = useState(0);
    const wrapperRef = useRef(null);
    const containerRef = useRef(null);
    const lastTimeRef = useRef(0);
    const indexRef = useRef(index);
    useEffect(() => {
        indexRef.current = 0;
        setIndex(0);
    }, [slides]);

    useEffect(() => {
        const onTorreStarted = () => {
            indexRef.current = 0;
            setIndex(0);
        };
        window.addEventListener('torre:started', onTorreStarted);
        return () => window.removeEventListener('torre:started', onTorreStarted);
    }, [slides]);

    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;

        const onWheel = (e) => {
            // Usar apenas delta horizontal para trocar slides via wheel.
            // Delta vertical e reservado para scroll interno dos slides — nao prevenir.
            const deltaH = e.deltaX;
            const deltaV = e.deltaY;

            // Se o movimento e predominantemente horizontal, trocar slide
            if (Math.abs(deltaH) > Math.abs(deltaV)) {
                const now = Date.now();
                if (now - lastTimeRef.current < 450) return;
                if (deltaH === 0) return;
                e.preventDefault();
                lastTimeRef.current = now;
                setIndex(i => {
                    const next = deltaH > 0 ? Math.min(i + 1, slides.length - 1) : Math.max(i - 1, 0);
                    indexRef.current = next;
                    return next;
                });
            }
            // Movimento vertical: nao faz nada — o browser/scroll interno cuida
        };

        el.addEventListener('wheel', onWheel, { passive: false });
        return () => el.removeEventListener('wheel', onWheel);
    }, [slides.length]);

    // touch swipe (horizontal only — vertical scroll is left to the browser)
    // Este bloco e o unico handler de touch do carousel; o segundo bloco abaixo foi removido.

    // no routing sync: carousel manages its own state and keeps page at top when switching
    useEffect(() => {
        window.scrollTo({ top: 0, behavior: 'auto' });
    }, [index, cardNodesVersion, slides]);

    // apply translateX on wrapper
    useEffect(() => {
        const w = wrapperRef.current;
        if (!w) return;
        w.style.transition = 'transform 0.8s cubic-bezier(.22,.9,.2,1)';
        w.style.transform = `translateX(${-index * 100}vw)`;
        indexRef.current = index;
    }, [index]);

    // start/stop analytics timers based on visible slide
    const visiblePageRef = useRef(null);
    const classeAboutRef = useRef(null);
    const aboutRootRef = useRef(null);
    const classeHomeRef = useRef(null);
    const homeRootRef = useRef(null);
    const classeProjectsRef = useRef(null);
    const projectsRootRef = useRef(null);
    const cardNodesRef = useRef(new Map());
    const removeTimersRef = useRef(new Map());

    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        
        // Detectar se é dispositivo touch
        const isTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
        
        // Se for dispositivo touch, não adicionar eventos de mouse
        if (isTouchDevice) {
            return;
        }
        
        let isDragging = false;
        let startX = 0;
        let startTime = 0;

        const onMouseDown = (e) => {
            isDragging = true;
            startX = e.clientX;
            startTime = Date.now();
            el.style.cursor = 'grabbing';
            e.preventDefault();
        };

        const onMouseMove = (e) => {
            if (!isDragging) return;
            e.preventDefault();
        };

        const onMouseUp = (e) => {
            if (!isDragging) return;
            isDragging = false;
            el.style.cursor = 'grab';
            
            const endX = e.clientX;
            const diff = startX - endX;
            const dt = Date.now() - startTime;
            
            // Se movimento > 50px e tempo < 1s, considerar como swipe
            if (Math.abs(diff) > 50 && dt < 1000) {
                if (diff > 0) {
                    // Drag para esquerda = próximo slide
                    setIndex(i => { 
                        const next = Math.min(i + 1, slides.length - 1); 
                        indexRef.current = next; 
                        return next; 
                    });
                } else {
                    // Drag para direita = slide anterior
                    setIndex(i => { 
                        const prev = Math.max(i - 1, 0); 
                        indexRef.current = prev; 
                        return prev; 
                    });
                }
            }
        };

        const onMouseLeave = () => {
            if (isDragging) {
                isDragging = false;
                el.style.cursor = 'grab';
            }
        };

        // Adicionar cursor grab por padrão
        el.style.cursor = 'grab';
        
        el.addEventListener('mousedown', onMouseDown);
        el.addEventListener('mousemove', onMouseMove);
        el.addEventListener('mouseup', onMouseUp);
        el.addEventListener('mouseleave', onMouseLeave);
        
        return () => {
            el.removeEventListener('mousedown', onMouseDown);
            el.removeEventListener('mousemove', onMouseMove);
            el.removeEventListener('mouseup', onMouseUp);
            el.removeEventListener('mouseleave', onMouseLeave);
        };
    }, [slides.length]);

    // Handler de touch: distingue swipe horizontal (troca slide) de scroll vertical (passa para o browser).
    // IMPORTANTE: todos os listeners sao passive: true — jamais chamamos preventDefault().
    // A decisao de qual slide ativar e feita inteiramente no touchend, com base em startX/startY
    // gravados no touchstart. O browser tem liberdade total para processar o scroll nativo
    // em paralelo, sem esperar o handler JS — isso e o que desbloqueia o scroll no iOS Safari.
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;

        let startX = 0;
        let startY = 0;
        let startTime = 0;

        const onTouchStart = (e) => {
            startX = e.touches[0].clientX;
            startY = e.touches[0].clientY;
            startTime = Date.now();
        };

        // touchmove apenas observa — nao chama preventDefault, nao bloqueia scroll nativo.
        // passive: true e obrigatorio aqui para que o iOS Safari nao suspenda o scroll
        // enquanto aguarda o retorno do handler JS.
        const onTouchMove = () => {
            // noop — so existe para que o browser saiba que nao ha preventDefault aqui.
            // A logica de swipe e decidida no touchend.
        };

        const onTouchEnd = (e) => {
            const endX = e.changedTouches[0].clientX;
            const endY = e.changedTouches[0].clientY;
            const diffX = startX - endX;
            const diffY = Math.abs(startY - endY);
            const dt = Date.now() - startTime;

            // So considera swipe horizontal se:
            // - deslocamento horizontal > 50px
            // - deslocamento vertical < deslocamento horizontal (gesto predominantemente lateral)
            // - duracao < 800ms
            if (Math.abs(diffX) > 50 && Math.abs(diffX) > diffY && dt < 800) {
                if (diffX > 0) {
                    setIndex(i => { const next = Math.min(i + 1, slides.length - 1); indexRef.current = next; return next; });
                } else {
                    setIndex(i => { const prev = Math.max(i - 1, 0); indexRef.current = prev; return prev; });
                }
            }
        };

        el.addEventListener('touchstart', onTouchStart, { passive: true });
        el.addEventListener('touchmove', onTouchMove, { passive: true });
        el.addEventListener('touchend', onTouchEnd, { passive: true });
        el.addEventListener('touchcancel', onTouchEnd, { passive: true });

        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('touchmove', onTouchMove);
            el.removeEventListener('touchend', onTouchEnd);
            el.removeEventListener('touchcancel', onTouchEnd);
        };
    }, [slides.length]);

    useEffect(() => {
        const slide = slides && slides[index];
        visiblePageRef.current = normalizarPageId(slide, index);

    }, [index, slides]);

    // manage page analytics lifecycle when the visible slide changes
    useEffect(() => {
        const slide = slides && slides[index];
        const page = normalizarPageId(slide, index);
        visiblePageRef.current = page;
        // find the card-carousel node for the current slide from the reported map
        const cardNode = cardNodesRef.current.get(index) || null;

        // manage page-specific controllers based on route path
        if (page === '/') {
            homeRootRef.current = cardNode || null;

            if (homeRootRef.current) {
                if (!classeHomeRef.current) {
                    classeHomeRef.current = new ClasseHome(homeRootRef.current);
                }

                if (classeHomeRef.current instanceof ClasseHome) {
                    if (!classeHomeRef.current.executando) {
                        try {
                            classeHomeRef.current.iniciar();
                        } catch { // pass
                        }
                    }
                } else {
                    //
                }
            }
        } else {
            if (classeHomeRef.current) {
                try {
                    classeHomeRef.current.parar();
                } catch {
                    //
                }
            }
        }

        if (page === '/about') {
            // only start when we have a real cardNode to attach to
            aboutRootRef.current = cardNode || null;
            if (aboutRootRef.current) {
                if (!classeAboutRef.current) {
                    classeAboutRef.current = new ClasseAbout(aboutRootRef.current);
                    try {
                        // Tentar iniciar - verificando qual método está disponível
                        if (typeof classeAboutRef.current.iniciar === 'function') {
                            classeAboutRef.current.iniciar();
                        } else if (typeof classeAboutRef.current.start === 'function') {
                            classeAboutRef.current.start();
                        }
                    } catch {
                        //
                    }
                } else {
                    if (classeAboutRef.current.root !== aboutRootRef.current)
                        classeAboutRef.current.root = aboutRootRef.current;

                    // Verificar se está executando
                    const isRunning =
                        (typeof classeAboutRef.current.executando === 'boolean' && classeAboutRef.current.executando) ||
                        (typeof classeAboutRef.current.running === 'boolean' && classeAboutRef.current.running);

                    if (!isRunning) {
                        try {
                            if (typeof classeAboutRef.current.iniciar === 'function') {
                                classeAboutRef.current.iniciar();
                            } else if (typeof classeAboutRef.current.start === 'function') {
                                classeAboutRef.current.start();
                            }
                        } catch {
                            //
                        }
                    }
                }
            }
        } else {
            if (classeAboutRef.current) {
                try {
                    if (typeof classeAboutRef.current.parar === 'function') {
                        classeAboutRef.current.parar();
                    } else if (typeof classeAboutRef.current.stop === 'function') {
                        classeAboutRef.current.stop();
                    }
                } catch {
                    //
                }
            }
        }

        if (page === '/projects') {
            projectsRootRef.current = cardNode || null;
            if (projectsRootRef.current) {
                if (!classeProjectsRef.current) {
                    classeProjectsRef.current = new ClasseProjects(projectsRootRef.current);
                    try {
                        if (typeof classeProjectsRef.current.iniciar === 'function') {
                            classeProjectsRef.current.iniciar();
                        } else if (typeof classeProjectsRef.current.start === 'function') {
                            classeProjectsRef.current.start();
                        }
                    } catch {
                        //
                    }
                } else {
                    if (classeProjectsRef.current.root !== projectsRootRef.current)
                        classeProjectsRef.current.root = projectsRootRef.current;

                    // Verificar se está executando
                    const isRunning =
                        (typeof classeProjectsRef.current.executando === 'boolean' && classeProjectsRef.current.executando) ||
                        (typeof classeProjectsRef.current.running === 'boolean' && classeProjectsRef.current.running);

                    if (!isRunning) {
                        try {
                            if (typeof classeProjectsRef.current.iniciar === 'function') {
                                classeProjectsRef.current.iniciar();
                            } else if (typeof classeProjectsRef.current.start === 'function') {
                                classeProjectsRef.current.start();
                            }
                        } catch {
                            //
                        }
                    }
                }
            }
        } else {
            if (classeProjectsRef.current) {
                try {
                    if (typeof classeProjectsRef.current.parar === 'function') {
                        classeProjectsRef.current.parar();
                    } else if (typeof classeProjectsRef.current.stop === 'function') {
                        classeProjectsRef.current.stop();
                    }
                } catch {
                    //
                }
            }
        }
    }, [index, cardNodesVersion, slides]);

    const handleNodeReady = useCallback((idx, node) => {
        const map = cardNodesRef.current;
        const timers = removeTimersRef.current;
        // if a pending remove timer exists for this idx, cancel it when node returns
        const pending = timers.get(idx);
        if (pending) {
            clearTimeout(pending);
            timers.delete(idx);
        }

        if (node) {
            map.set(idx, node);
            setCardNodesVersion(v => v + 1);
            return;
        }

        // schedule removal after short delay -- avoids transient stop/start caused by remount/double-render in dev
        const t = setTimeout(() => {
            try {
                map.delete(idx);
                setCardNodesVersion(v => v + 1);
            } finally {
                removeTimersRef.current.delete(idx);
            }
        }, 150);
        timers.set(idx, t);
    }, []);

    useEffect(() => {
        const onKey = (e) => {
            if (e.key === 'ArrowRight') {
                setIndex(i => { const next = Math.min(i + 1, slides.length - 1); indexRef.current = next; return next; });
            } else if (e.key === 'ArrowLeft') {
                setIndex(i => { const prev = Math.max(i - 1, 0); indexRef.current = prev; return prev; });
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [slides.length]);

    // cleanup ClasseAbout on unmount
    useEffect(() => {
        return () => {
            if (classeAboutRef.current) {
                try {
                    if (typeof classeAboutRef.current.parar === 'function') {
                        classeAboutRef.current.parar();
                    } else if (typeof classeAboutRef.current.stop === 'function') {
                        classeAboutRef.current.stop();
                    }
                } catch {
                    //
                }
            }
            if (classeHomeRef.current) {
                try {
                    if (typeof classeHomeRef.current.parar === 'function') {
                        classeHomeRef.current.parar();
                    } else if (typeof classeHomeRef.current.stop === 'function') {
                        classeHomeRef.current.stop();
                    }
                } catch {
                    //
                }
            }
            if (classeProjectsRef.current) {
                try {
                    if (typeof classeProjectsRef.current.parar === 'function') {
                        classeProjectsRef.current.parar();
                    } else if (typeof classeProjectsRef.current.stop === 'function') {
                        classeProjectsRef.current.stop();
                    }
                } catch {
                    // 
                }
            }
        };
    }, []);

    const goPrev = useCallback(() => {
        setIndex(cur => { const prev = Math.max(cur - 1, 0); indexRef.current = prev; return prev; });
    }, []);
    const goNext = useCallback(() => {
        setIndex(cur => { const next = Math.min(cur + 1, slides.length - 1); indexRef.current = next; return next; });
    }, [slides.length]);
    const goTo = useCallback((target) => {
        setIndex(() => { const next = Math.max(0, Math.min(target, slides.length - 1)); indexRef.current = next; return next; });
    }, [slides.length]);

    return (
        // overflow: hidden confina o carrossel a exatamente 100dvh — impede scroll do documento.
        // O scroll vertical fica em .page-root (overflow-y: auto) dentro de cada SlideItem.
        // touchAction: pan-y sinaliza ao browser que gestos verticais devem ser tratados como scroll nativo.
        <div ref={containerRef} className="carousel-root" style={{ position: 'relative', width: '100%', height: '100dvh', overflow: 'hidden', touchAction: 'pan-y' }}>
            <div ref={wrapperRef} style={{ display: 'flex', flexDirection: 'row', width: `${slides.length * 100}vw`, height: '100%', willChange: 'transform', alignItems: 'flex-start' }}>
                {slides.map((s, i) => (
                    <SlideItem key={s.path} slide={s} idx={i} total={slides.length}
                        onNodeReady={handleNodeReady}
                    />
                ))}
            </div>

            <nav className="carousel-pager" aria-label="Navegacao entre slides">
                <button
                    type="button"
                    className="carousel-pager__btn carousel-pager__btn--prev"
                    aria-label="Slide anterior"
                    onClick={goPrev}
                    disabled={index === 0}
                >
                    ‹
                </button>
                <ol className="carousel-pager__dots" role="tablist">
                    {slides.map((s, i) => (
                        <li key={s.path} role="presentation">
                            <button
                                type="button"
                                role="tab"
                                aria-selected={i === index}
                                aria-label={`Ir para ${s.label ?? s.path ?? `slide ${i + 1}`}`}
                                className={`carousel-pager__dot${i === index ? ' carousel-pager__dot--active' : ''}`}
                                onClick={() => goTo(i)}
                            />
                        </li>
                    ))}
                </ol>
                <button
                    type="button"
                    className="carousel-pager__btn carousel-pager__btn--next"
                    aria-label="Proximo slide"
                    onClick={goNext}
                    disabled={index === slides.length - 1}
                >
                    ›
                </button>
            </nav>
        </div>
    );
}

function normalizarPageId(slide, index) {
    const rawPageId = slide && (slide.path || slide.id || `/slide-${index}`);
    if (typeof rawPageId !== 'string') {
        return `/slide-${index}`;
    }

    const semQuery = rawPageId.split(/[?#]/)[0] || '/';
    return semQuery.startsWith('/') ? semQuery : `/${semQuery}`;
}

function SlideItem({ slide, idx, onNodeReady }) {
    const rootRef = useRef(null);

    useLayoutEffect(() => {
        const root = rootRef.current;
        if (!root) return;
        const node = root.querySelector('.card-carousel');
        if (node) {
            if (!node.style.position || node.style.position === 'static') node.style.position = 'relative';
            if (onNodeReady) onNodeReady(idx, node);
        }
    }, [idx, onNodeReady]);

    useEffect(() => {
        return () => {
            if (onNodeReady) onNodeReady(idx, null);
        };
    }, [idx, onNodeReady]);

    return (
        // height: 100dvh + overflow: hidden — cada slide ocupa exatamente a viewport e nao vaza.
        // O scroll vertical fica em .page-root (overflow-y: auto), nunca no documento.
        <div ref={rootRef} style={{ width: '100vw', height: '100dvh', overflow: 'hidden', flexShrink: 0 }}>
            <div style={{ width: '100%', height: '100%' }}>{slide.element}</div>
        </div>
    );
}
