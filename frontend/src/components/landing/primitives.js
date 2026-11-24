import React, { useCallback, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

/* ------------------------------------------------------------------ */
/* Motion preferences                                                  */
/* ------------------------------------------------------------------ */

export function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(
    () => typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => setReduced(mq.matches);
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else mq.addListener(onChange);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', onChange);
      else mq.removeListener(onChange);
    };
  }, []);

  return reduced;
}

/* ------------------------------------------------------------------ */
/* In-view detection (pauses offscreen animation, triggers reveals)    */
/* ------------------------------------------------------------------ */

export function useInView({ threshold = 0.25, once = false } = {}) {
  const ref = useRef(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver !== 'function') {
      setInView(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setInView(true);
            if (once) observer.disconnect();
          } else if (!once) {
            setInView(false);
          }
        });
      },
      { threshold }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [threshold, once]);

  return [ref, inView];
}

/* ------------------------------------------------------------------ */
/* Typewriter — used by hero answer + product demo. Pauses offscreen,  */
/* renders instantly under prefers-reduced-motion.                     */
/* ------------------------------------------------------------------ */

export function useTypewriter(text, { active = true, cps = 42, startDelay = 350 } = {}) {
  const reduced = usePrefersReducedMotion();
  const [count, setCount] = useState(reduced ? text.length : 0);
  const done = count >= text.length;

  useEffect(() => {
    if (reduced) {
      setCount(text.length);
      return undefined;
    }
    if (!active) {
      setCount(0);
      return undefined;
    }
    setCount(0);
    let interval = null;
    const startTimer = setTimeout(() => {
      let i = 0;
      interval = setInterval(() => {
        i += 1;
        setCount(i);
        if (i >= text.length && interval) clearInterval(interval);
      }, 1000 / cps);
    }, startDelay);
    return () => {
      clearTimeout(startTimer);
      if (interval) clearInterval(interval);
    };
  }, [text, active, reduced, cps, startDelay]);

  return { text: reduced ? text : text.slice(0, count), done: reduced || done };
}

/* ------------------------------------------------------------------ */
/* Magnetic hover for hero CTA (transform-only, rAF-free, pointer gap) */
/* ------------------------------------------------------------------ */

export function useMagnetic(strength = 10) {
  const ref = useRef(null);
  const reduced = usePrefersReducedMotion();

  const onMove = useCallback(
    (event) => {
      const el = ref.current;
      if (!el || reduced) return;
      const rect = el.getBoundingClientRect();
      const relX = (event.clientX - rect.left) / rect.width - 0.5;
      const relY = (event.clientY - rect.top) / rect.height - 0.5;
      el.style.transform = `translate(${relX * strength}px, ${relY * strength}px)`;
    },
    [reduced, strength]
  );

  const onLeave = useCallback(() => {
    const el = ref.current;
    if (el) el.style.transform = '';
  }, []);

  return { ref, onPointerMove: onMove, onPointerLeave: onLeave };
}

/* ------------------------------------------------------------------ */
/* Shared presentational primitives                                    */
/* ------------------------------------------------------------------ */

export function Reveal({ children, delay = 0, y = 28, className, as = 'div' }) {
  const reduced = usePrefersReducedMotion();
  const Component = motion[as] || motion.div;

  if (reduced) {
    const Tag = as;
    return <Tag className={className}>{children}</Tag>;
  }

  return (
    <Component
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.7, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </Component>
  );
}

export function GlassPanel({ children, className, depth = 'default', as: Tag = 'div', ...rest }) {
  return (
    <Tag className={cn('fsl-glass', depth === 'deep' && 'fsl-glass--deep', className)} {...rest}>
      {children}
    </Tag>
  );
}

export function SectionHeading({ id, eyebrow, title, lede, align = 'center' }) {
  return (
    <Reveal className={cn('fsl-section-head', align === 'left' && 'fsl-section-head--left')}>
      <p className="fsl-eyebrow">{eyebrow}</p>
      <h2 className="fsl-h2" id={id ? `${id}-title` : undefined}>
        {title}
      </h2>
      {lede ? <p className="fsl-lede">{lede}</p> : null}
    </Reveal>
  );
}
