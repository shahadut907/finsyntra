import Section from "../primitives/Section";
import Reveal from "../primitives/Reveal";
import "./TechStack.css";

const LAYERS = [
  {
    key: "client",
    name: "Client",
    tech: "React",
    desc: "streaming chat interface",
    hue: "cyan",
  },
  {
    key: "api",
    name: "API",
    tech: "FastAPI · JWT",
    desc: "auth, RBAC, tenant scoping",
    hue: "blue",
  },
  {
    key: "intelligence",
    name: "Intelligence",
    tech: "RAG · local LLM (Ollama)",
    desc: "grounded reasoning",
    hue: "violet",
  },
  {
    key: "knowledge",
    name: "Knowledge",
    tech: "ChromaDB",
    desc: "vector search over your corpus",
    hue: "emerald",
  },
];

/**
 * Architecture as a system line — one glance for technical audiences,
 * without turning the page into a README.
 */
export default function TechStack() {
  return (
    <Section
      id="stack"
      eyebrow="Technology"
      title={
        <>
          A full-stack <em>intelligence architecture.</em>
        </>
      }
      lead="Every layer runs on infrastructure you control — the language model included."
      align="center"
    >
      <Reveal>
        <div className="stack glass">
          <ol className="stack__line" aria-label="System architecture layers">
            {LAYERS.map((l, i) => (
              <li key={l.key} className={`stack__layer stack__layer--${l.hue}`}>
                <span className="stack__layer-dot" aria-hidden="true" />
                <span className="stack__layer-name">{l.name}</span>
                <span className="stack__layer-tech mono">{l.tech}</span>
                <span className="stack__layer-desc">{l.desc}</span>
                {i < LAYERS.length - 1 && (
                  <span className="stack__arrow" aria-hidden="true">
                    <svg viewBox="0 0 40 12" width="40" height="12">
                      <path d="M0 6 H32 M27 1.5 L33 6 L27 10.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                )}
              </li>
            ))}
          </ol>

          <div className="stack__chips">
            <span className="stack__chip mono">SSE streaming</span>
            <span className="stack__chip mono">httpOnly cookies</span>
            <span className="stack__chip mono">multi-tenant</span>
            <span className="stack__chip mono">conversation memory</span>
            <span className="stack__chip mono">PDF · JSON · MD export</span>
          </div>
        </div>
      </Reveal>
    </Section>
  );
}
