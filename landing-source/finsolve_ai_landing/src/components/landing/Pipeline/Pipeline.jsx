import { useEffect, useRef, useState } from "react";
import Section from "../primitives/Section";
import Reveal from "../primitives/Reveal";
import useInView from "../../../hooks/useInView";
import useReducedMotion from "../../../hooks/useReducedMotion";
import "./Pipeline.css";

const STAGES = [
  {
    key: "upload",
    label: "Upload",
    icon: (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path d="M12 15 V4 M7.5 8.5 L12 4 L16.5 8.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M4.5 15.5 v3 a2 2 0 0 0 2 2 h11 a2 2 0 0 0 2 -2 v-3" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    ),
    plain: "Documents enter the workspace — financial reports, budgets, analyses.",
    tech: "PDF · CSV · DOCX · Markdown",
  },
  {
    key: "understand",
    label: "Understand",
    icon: (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <rect x="5" y="3.5" width="14" height="17" rx="2" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path d="M8.5 8 h7 M8.5 12 h7 M8.5 16 h4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    ),
    plain: "Text is extracted and split into meaningful passages.",
    tech: "parsing · chunking",
  },
  {
    key: "embed",
    label: "Embed",
    icon: (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <circle cx="6" cy="6" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <circle cx="18" cy="6" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <circle cx="12" cy="18" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path d="M7.7 7.3 L10.6 16 M16.3 7.3 L13.4 16 M8.2 6 h7.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    ),
    plain: "Each passage becomes a vector — a mathematical fingerprint of its meaning.",
    tech: "embeddings",
  },
  {
    key: "retrieve",
    label: "Retrieve",
    icon: (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path d="M15.5 15.5 L20 20" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
      </svg>
    ),
    plain: "When you ask, the most relevant passages from your documents are found.",
    tech: "ChromaDB · vector search",
  },
  {
    key: "reason",
    label: "Reason",
    icon: (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path d="M12 3 L21 12 L12 21 L3 12 Z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
        <path d="M12 7.5 L16.5 12 L12 16.5 L7.5 12 Z" fill="currentColor" opacity="0.65" />
      </svg>
    ),
    plain: "The language model composes an answer from those passages — nothing else.",
    tech: "local LLM · Ollama",
  },
  {
    key: "answer",
    label: "Answer",
    icon: (
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path d="M4 6 h16 v10 h-8.5 L7 20 v-4 H4 Z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
        <path d="M8.5 11 h7" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    ),
    plain: "A grounded response streams in live, with its sources attached.",
    tech: "SSE streaming · exports",
  },
];

/**
 * The RAG journey — six stages on a flowing rail. The active stage
 * auto-advances while visible; selecting a stage reveals its detail.
 */
export default function Pipeline() {
  const [sectionRef, inView] = useInView({ threshold: 0.3 });
  const reduced = useReducedMotion();
  const [active, setActive] = useState(0);
  const pausedUntil = useRef(0);

  useEffect(() => {
    if (reduced || !inView) return undefined;
    const id = setInterval(() => {
      if (Date.now() < pausedUntil.current || document.hidden) return;
      setActive((a) => (a + 1) % STAGES.length);
    }, 2600);
    return () => clearInterval(id);
  }, [inView, reduced]);

  const select = (i) => {
    setActive(i);
    pausedUntil.current = Date.now() + 9000;
  };

  return (
    <Section
      id="intelligence"
      eyebrow="Intelligence"
      title={
        <>
          Answers grounded in <em>organizational knowledge.</em>
        </>
      }
      lead="FinSyntra never answers from memory of the open internet. Every response travels a retrieval-augmented pipeline — from your documents, through meaning-preserving vectors, to a cited answer."
    >
      <div ref={sectionRef} className="pipeline">
        <Reveal>
          <div className="pipeline__rail glass" role="tablist" aria-label="RAG pipeline stages">
            {STAGES.map((s, i) => {
              const isActive = i === active;
              const isPast = i < active;
              return (
                <button
                  key={s.key}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  className={`pipeline__stage ${isActive ? "is-active" : ""} ${isPast ? "is-past" : ""}`}
                  onClick={() => select(i)}
                >
                  <span className="pipeline__node" aria-hidden="true">
                    {s.icon}
                  </span>
                  <span className="pipeline__stage-label">{s.label}</span>
                  <span className="pipeline__stage-index mono">{String(i + 1).padStart(2, "0")}</span>
                  {i < STAGES.length - 1 && <span className="pipeline__seg" aria-hidden="true"><span className="pipeline__seg-flow" /></span>}
                </button>
              );
            })}
          </div>
        </Reveal>

        <Reveal delay={0.15}>
          <div className="pipeline__detail glass-lite" aria-live="polite">
            <div className="pipeline__detail-head">
              <span className="pipeline__detail-stage mono">
                stage {active + 1} / {STAGES.length}
              </span>
              <span className="pipeline__detail-tech mono">{STAGES[active].tech}</span>
            </div>
            <p className="pipeline__detail-text" key={STAGES[active].key}>
              {STAGES[active].plain}
            </p>
            <div className="pipeline__progress" aria-hidden="true">
              {STAGES.map((s, i) => (
                <span key={s.key} className={`pipeline__progress-dot ${i === active ? "is-on" : ""}`} />
              ))}
            </div>
          </div>
        </Reveal>
      </div>
    </Section>
  );
}
