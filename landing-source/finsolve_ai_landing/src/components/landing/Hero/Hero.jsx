import { useEffect, useRef } from "react";
import CTAButton from "../primitives/CTAButton";
import useInView from "../../../hooks/useInView";
import useReducedMotion from "../../../hooks/useReducedMotion";
import { APP_LOGIN_URL } from "../../../appUrl";
import "./Hero.css";

const STREAM_SENTENCE =
  "Operating expenses rose 8.4% quarter-over-quarter — infrastructure and hiring drove the increase.";

const FORMATS = ["PDF", "CSV", "DOCX", "MD"];

/**
 * Hero — cinematic product introduction.
 * Left: positioning copy + CTA hierarchy.
 * Right: a live "intelligence workspace" showing document → retrieval →
 * reasoning → streaming answer, with a cursor-responsive light.
 */
export default function Hero() {
  const [visualRef, inView] = useInView({ threshold: 0.2 });
  const reduced = useReducedMotion();
  const lightRef = useRef(null);
  const streamRef = useRef(null);
  const rafRef = useRef(0);

  // Cursor-responsive lighting (fine pointers only, reduced motion respected)
  useEffect(() => {
    const fine = window.matchMedia("(pointer: fine)").matches;
    if (!fine || reduced) return undefined;
    const hero = visualRef.current;
    if (!hero) return undefined;

    const onMove = (e) => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        const rect = hero.getBoundingClientRect();
        const el = lightRef.current;
        if (el) {
          el.style.setProperty("--mx", `${e.clientX - rect.left}px`);
          el.style.setProperty("--my", `${e.clientY - rect.top}px`);
          el.style.opacity = "1";
        }
      });
    };

    const onLeave = () => {
      if (lightRef.current) lightRef.current.style.opacity = "0";
    };

    hero.addEventListener("pointermove", onMove);
    hero.addEventListener("pointerleave", onLeave);
    return () => {
      cancelAnimationFrame(rafRef.current);
      hero.removeEventListener("pointermove", onMove);
      hero.removeEventListener("pointerleave", onLeave);
    };
  }, [reduced, visualRef]);

  // Streaming answer loop — only while visible, skipped for reduced motion
  useEffect(() => {
    const el = streamRef.current;
    if (!el || reduced) return undefined;

    let timer;
    let i = 0;
    let alive = true;

    const tick = () => {
      if (!alive) return;
      if (!document.hidden && inView) {
        i += 1;
        if (i > STREAM_SENTENCE.length) {
          // hold the finished sentence, then restart
          timer = setTimeout(() => {
            i = 0;
            el.textContent = "";
            timer = setTimeout(tick, 500);
          }, 5200);
          return;
        }
        el.textContent = STREAM_SENTENCE.slice(0, i);
        timer = setTimeout(tick, 26 + Math.random() * 30);
      } else {
        timer = setTimeout(tick, 800);
      }
    };

    if (inView) timer = setTimeout(tick, 1200);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [inView, reduced]);

  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="container hero__grid">
        {/* ---------------- Copy ---------------- */}
        <div className="hero__copy">
          <p className="hero__eyebrow anim" style={{ "--d": "0.05s" }}>
            <span className="dot dot--pulse" aria-hidden="true" />
            RAG-powered financial intelligence
          </p>

          <h1 id="hero-title" className="display display-xl hero__title">
            <span className="anim" style={{ "--d": "0.14s" }}>

              Financial
            </span>
            <span className="anim" style={{ "--d": "0.22s" }}>
              intelligence,
            </span>
            <span className="anim" style={{ "--d": "0.3s" }}>
              <em className="text-gradient">grounded</em> in
            </span>
            <span className="anim" style={{ "--d": "0.38s" }}>
              your data.
            </span>
          </h1>

          <p className="lead hero__lead anim" style={{ "--d": "0.5s" }}>
            FinSyntra turns your organization&apos;s financial documents into secure, contextual answers —
            retrieved from your own knowledge, reasoned by AI, streamed in real time.
          </p>

          <div className="hero__ctas anim" style={{ "--d": "0.62s" }}>
            <CTAButton href={APP_LOGIN_URL} size="lg">
              Explore FinSyntra
              <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
                <path d="M3 8 h10 M9 4 l4 4 -4 4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </CTAButton>
            <CTAButton href="#intelligence" variant="ghost" size="lg" magnetic={false}>
              See how it works
            </CTAButton>
          </div>

          <div className="hero__formats anim" style={{ "--d": "0.74s" }}>
            <span className="hero__formats-label">Works with</span>
            <ul>
              {FORMATS.map((f) => (
                <li key={f} className="mono">{f}</li>
              ))}
              <li className="hero__langs">
                <span lang="bn" className="bn">বাংলা</span> · English
              </li>
            </ul>
          </div>
        </div>

        {/* ---------------- Visual ---------------- */}
        <div className="hero__visual anim" style={{ "--d": "0.45s" }} ref={visualRef}>
          <div className="hero__light" ref={lightRef} aria-hidden="true" />

          {/* faint market line behind the console */}
          <svg className="hero__market" viewBox="0 0 520 220" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="hero-line" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0" stopColor="#38d6f5" stopOpacity="0" />
                <stop offset="0.5" stopColor="#7db0ff" stopOpacity="0.5" />
                <stop offset="1" stopColor="#a78bfa" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path
              d="M0 190 L60 172 L110 181 L170 140 L230 152 L290 108 L350 122 L410 74 L470 88 L520 40"
              fill="none"
              stroke="url(#hero-line)"
              strokeWidth="1.6"
              className="hero__market-path"
            />
          </svg>

          {/* The intelligence workspace */}
          <div className="hero__console glass-deep">
            <div className="hero__console-head">
              <span className="hero__console-title mono">FinSyntra Intelligence</span>
              <span className="pill hero__live-pill">
                <span className="dot dot--pulse" aria-hidden="true" />
                demo
              </span>
            </div>

            <div className="hero__flow">
              {/* 1 — Document */}
              <div className="hero__node hero__node--doc">
                <span className="hero__node-icon" aria-hidden="true">
                  <svg viewBox="0 0 20 20" width="16" height="16">
                    <path d="M5 2.5 h7 L16 6.5 v11 H5 Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                    <path d="M12 2.5 v4 h4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                  </svg>
                </span>
                <span className="hero__node-text">
                  <strong>Q3 Financial Report.pdf</strong>
                  <small className="mono">organizational knowledge</small>
                </span>
              </div>

              <FlowConnector />

              {/* 2 — Retrieval */}
              <div className="hero__node hero__node--retrieve">
                <span className="hero__ring" aria-hidden="true">
                  <span className="hero__ring-core">
                    <svg viewBox="0 0 20 20" width="14" height="14">
                      <circle cx="9" cy="9" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
                      <path d="M13.2 13.2 L17 17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                    </svg>
                  </span>
                </span>
                <span className="hero__node-text">
                  <strong>Knowledge retrieval</strong>
                  <small className="mono">3 passages matched</small>
                </span>
              </div>

              <FlowConnector />

              {/* 3 — Reasoning core */}
              <div className="hero__node hero__node--core">
                <span className="hero__core" aria-hidden="true">
                  <span className="hero__core-orb">
                    <svg viewBox="0 0 24 24" width="15" height="15">
                      <path d="M12 3 L21 12 L12 21 L3 12 Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                      <path d="M12 8 L16 12 L12 16 L8 12 Z" fill="currentColor" opacity="0.7" />
                    </svg>
                  </span>
                  <span className="hero__core-wave hero__core-wave--1" />
                  <span className="hero__core-wave hero__core-wave--2" />
                </span>
                <span className="hero__node-text">
                  <strong>Grounded reasoning</strong>
                  <small className="mono">local LLM · Ollama</small>
                </span>
              </div>

              <FlowConnector active />

              {/* 4 — Streaming answer */}
              <div className="hero__node hero__node--answer">
                <span className="hero__node-icon hero__node-icon--aqua" aria-hidden="true">
                  <svg viewBox="0 0 20 20" width="16" height="16">
                    <path d="M3 4.5 h14 v8 H9 L5.5 16 v-3.5 H3 Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                  </svg>
                </span>
                <span className="hero__node-text">
                  <span className="hero__stream">
                    <span ref={streamRef} className="hero__stream-text">
                      {reduced ? STREAM_SENTENCE : ""}
                    </span>
                    <span className="hero__caret" aria-hidden="true" />
                  </span>
                  <small>
                    <span className="hero__cite mono">Q3 Report §4.2</span>
                    <span className="hero__cite hero__cite--csv mono">Budget.csv</span>
                  </small>
                </span>
              </div>
            </div>
          </div>

          {/* Floating badges */}
          <div className="hero__badge hero__badge--sources glass" aria-hidden="true">
            <svg viewBox="0 0 16 16" width="13" height="13">
              <path d="M8 1.5 L14 4.5 v4 c0 3-2.5 5-6 6.5 C4.5 13.5 2 11.5 2 8.5 v-4 Z" fill="none" stroke="#34d399" strokeWidth="1.4" strokeLinejoin="round" />
              <path d="M5.5 8 l1.8 1.8 L11 6" fill="none" stroke="#34d399" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            grounded in 3 sources
          </div>

          <div className="hero__badge hero__badge--tenant glass" aria-hidden="true">
            <svg viewBox="0 0 16 16" width="13" height="13">
              <rect x="3" y="7.5" width="10" height="6.5" rx="1.4" fill="none" stroke="#7db0ff" strokeWidth="1.4" />
              <path d="M5.5 7.5 V5.2 a2.5 2.5 0 0 1 5 0 V7.5" fill="none" stroke="#7db0ff" strokeWidth="1.4" />
            </svg>
            tenant-isolated
          </div>

          <div className="hero__badge hero__badge--sse mono" aria-hidden="true">
            SSE stream
          </div>
        </div>
      </div>
    </section>
  );
}

/** Animated vertical connector between pipeline nodes. */
function FlowConnector({ active = false }) {
  return (
    <span className={`hero__connector ${active ? "hero__connector--active" : ""}`} aria-hidden="true">
      <span className="hero__connector-track" />
      <span className="hero__connector-pulse" />
    </span>
  );
}
