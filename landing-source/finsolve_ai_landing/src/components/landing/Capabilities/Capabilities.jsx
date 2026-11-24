import Section from "../primitives/Section";
import Reveal from "../primitives/Reveal";
import "./Capabilities.css";

/* Small presentational bits shared inside the bento cards */

function MiniIcon({ children, hue = "blue" }) {
  return <span className={`cap-icon cap-icon--${hue}`} aria-hidden="true">{children}</span>;
}

/**
 * Capabilities told as an asymmetric editorial grid — one large feature
 * story (grounded answers) plus five supporting panels, each with its own
 * micro-visual instead of repeated identical cards.
 */
export default function Capabilities() {
  return (
    <Section
      id="platform"
      eyebrow="Platform"
      title={
        <>
          Built for <em>financial truth,</em> not chatbot noise.
        </>
      }
      lead="Six capabilities that turn documents into dependable intelligence — every one visible in the product, none decorative."
    >
      <div className="bento">
        {/* -------- Grounded AI (feature story) -------- */}
        <Reveal className="bento__cell bento__cell--grounded glass glass-interactive">
          <MiniIcon hue="violet">
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M12 3 L21 12 L12 21 L3 12 Z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
              <path d="M12 7.5 L16.5 12 L12 16.5 L7.5 12 Z" fill="currentColor" opacity="0.65" />
            </svg>
          </MiniIcon>
          <h3 className="bento__title">Grounded AI</h3>
          <p className="bento__desc">
            Every answer is composed from passages retrieved from your indexed organizational documents — with the
            sources attached, so figures can always be traced back.
          </p>
          <div className="bento__qa" aria-hidden="true">
            <p className="bento__qa-q">“Which departments exceeded Q3 budget?”</p>
            <p className="bento__qa-a">
              Two departments exceeded their Q3 allocation —
              <span className="bento__qa-figure"> Marketing (+12%)</span> and
              <span className="bento__qa-figure"> Infrastructure (+8%)</span>.
              <sup className="bento__qa-cite">1</sup>
              <sup className="bento__qa-cite">2</sup>
            </p>
            <div className="bento__qa-sources mono">
              <span>Budget.csv</span>
              <span>Q3 Report.pdf</span>
            </div>
          </div>
          <div className="bento__trace" aria-hidden="true">
            <span className="bento__trace-bar" style={{ "--w": "58%" }} />
            <span className="bento__trace-bar bento__trace-bar--hl" style={{ "--w": "86%" }} />
            <span className="bento__trace-bar" style={{ "--w": "41%" }} />
            <span className="bento__trace-note mono">passages ranked by relevance → composed into the answer</span>
          </div>
        </Reveal>

        {/* -------- Conversation memory -------- */}
        <Reveal delay={0.08} className="bento__cell bento__cell--memory glass glass-interactive">
          <MiniIcon hue="cyan">
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M4 6 a4 4 0 0 1 4 -4 h8 a4 4 0 0 1 4 4 v6 a4 4 0 0 1 -4 4 h-6 l-4 4 v-4 a4 4 0 0 1 -2 -3.5 Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
              <path d="M9 8 h6 M9 11.5 h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </MiniIcon>
          <h3 className="bento__title">Conversation memory</h3>
          <p className="bento__desc">Follow-up questions keep their context — entities, intent, and prior turns.</p>
          <div className="bento__thread" aria-hidden="true">
            <p className="bento__thread-q">…and compared to Q2?</p>
            <p className="bento__thread-a">
              Overspend narrowed from <span className="bento__qa-figure">19%</span> to{" "}
              <span className="bento__qa-figure">8%</span> — context carried from your previous question.
            </p>
          </div>
        </Reveal>

        {/* -------- Streaming -------- */}
        <Reveal delay={0.12} className="bento__cell glass glass-interactive">
          <MiniIcon hue="blue">
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M3.5 12 h4 l2.5 -6 4 12 2.5 -6 h4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </MiniIcon>
          <h3 className="bento__title">Real-time streaming</h3>
          <p className="bento__desc">Responses arrive continuously over server-sent events — no waiting for a full page.</p>
          <div className="bento__stream mono" aria-hidden="true">
            <span className="bento__stream-shimmer">retrieval matched · composing · streaming</span>
            <span className="bento__caret" />
          </div>
        </Reveal>

        {/* -------- Document intelligence -------- */}
        <Reveal delay={0.16} className="bento__cell glass glass-interactive">
          <MiniIcon hue="emerald">
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M6 3 h9 l4 4 v14 H6 Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
              <path d="M14.5 3 v4.5 H19" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
              <path d="M9 13 l2 2 4 -4.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </MiniIcon>
          <h3 className="bento__title">Document intelligence</h3>
          <p className="bento__desc">Parsed, chunked, and indexed — automatically.</p>
          <ul className="bento__formats mono" aria-hidden="true">
            <li>PDF</li>
            <li>CSV</li>
            <li>DOCX</li>
            <li>MD</li>
          </ul>
        </Reveal>

        {/* -------- Multilingual -------- */}
        <Reveal delay={0.2} className="bento__cell bento__cell--lang glass glass-interactive">
          <MiniIcon hue="magenta">
            <svg viewBox="0 0 24 24" width="20" height="20">
              <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
              <path d="M3.5 12 h17 M12 3.5 c2.6 2.4 3.9 5.3 3.9 8.5 s-1.3 6.1 -3.9 8.5 c-2.6 -2.4 -3.9 -5.3 -3.9 -8.5 s1.3 -6.1 3.9 -8.5 Z" fill="none" stroke="currentColor" strokeWidth="1.4" />
            </svg>
          </MiniIcon>
          <h3 className="bento__title">Bilingual intelligence</h3>
          <p className="bento__desc">Ask in English or Bangla — FinSyntra reasons in the language of your documents.</p>
          <div className="bento__langs" aria-hidden="true">
            <span className="mono">EN · revenue summary</span>
            <span className="bn" lang="bn">বাং · ব্যয় বিশ্লেষণ</span>
          </div>
        </Reveal>

        {/* -------- Exports -------- */}
        <Reveal delay={0.24} className="bento__cell bento__cell--export glass glass-interactive">
          <MiniIcon hue="aqua">
            <svg viewBox="0 0 24 24" width="20" height="20">
              <path d="M12 4 v11 M7.5 10.5 L12 15 l4.5 -4.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M4.5 16 v2.5 a2 2 0 0 0 2 2 h11 a2 2 0 0 0 2 -2 V16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </MiniIcon>
          <h3 className="bento__title">Exportable insights</h3>
          <p className="bento__desc">Any result leaves FinSyntra in the format your workflow needs.</p>
          <div className="bento__exports mono" aria-hidden="true">
            <span className="bento__export">
              <svg viewBox="0 0 16 16" width="11" height="11"><path d="M8 3 v7 M5 7.5 L8 10.5 L11 7.5 M4 12.5 h8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              PDF
            </span>
            <span className="bento__export">
              <svg viewBox="0 0 16 16" width="11" height="11"><path d="M8 3 v7 M5 7.5 L8 10.5 L11 7.5 M4 12.5 h8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              JSON
            </span>
            <span className="bento__export">
              <svg viewBox="0 0 16 16" width="11" height="11"><path d="M8 3 v7 M5 7.5 L8 10.5 L11 7.5 M4 12.5 h8" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              Markdown
            </span>
          </div>
        </Reveal>
      </div>
    </Section>
  );
}
