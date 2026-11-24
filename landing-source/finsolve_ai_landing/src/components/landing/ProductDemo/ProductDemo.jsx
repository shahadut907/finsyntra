import { useEffect, useState } from "react";
import Section from "../primitives/Section";
import Reveal from "../primitives/Reveal";
import useInView from "../../../hooks/useInView";
import useReducedMotion from "../../../hooks/useReducedMotion";
import "./ProductDemo.css";

const QUESTION = "Compare Q3 operating expenses with the previous quarter.";

const SOURCES = [
  { name: "Q3 Financial Report.pdf", type: "PDF", score: 94, hue: "blue" },
  { name: "Department Budget.csv", type: "CSV", score: 88, hue: "emerald" },
  { name: "Expense Analysis.docx", type: "DOCX", score: 81, hue: "violet" },
];

/* Answer tokens: b = bold figure, c = citation superscript */
const ANSWER = [
  { t: "Q3" }, { t: "operating" }, { t: "expenses" }, { t: "were" },
  { t: "$4.82M,", b: true }, { t: "up" }, { t: "8.4%", b: true }, { t: "from" },
  { t: "Q2" }, { t: "($4.45M)." }, { t: "The" }, { t: "increase" }, { t: "came" },
  { t: "mostly" }, { t: "from" }, { t: "infrastructure" }, { t: "(+$210K)", b: true },
  { t: "and" }, { t: "engineering" }, { t: "hiring" }, { t: "(+$140K),", b: true },
  { t: "partly" }, { t: "offset" }, { t: "by" }, { t: "a" }, { t: "6%", b: true },
  { t: "drop" }, { t: "in" }, { t: "travel." }, { t: "Spending" }, { t: "stayed" },
  { t: "within" }, { t: "the" }, { t: "revised" }, { t: "budget" }, { t: "envelope." },
  { c: 1 }, { c: 2 }, { c: 3 },
];

const PHASES = {
  typing: "typing",
  retrieving: "retrieving",
  streaming: "streaming",
  done: "done",
  reset: "reset",
};

/**
 * Interactive product showcase: a scripted but faithful recreation of the
 * FinSyntra chat experience — question typed, sources retrieved with
 * relevance, grounded answer streamed word-by-word, then export options.
 * Pauses off-screen and collapses to a static transcript under reduced motion.
 */
export default function ProductDemo() {
  const [sectionRef, inView] = useInView({ threshold: 0.2 });
  const reduced = useReducedMotion();
  const [runKey, setRunKey] = useState(0);

  // Static end-state when motion is reduced
  const [phase, setPhase] = useState(reduced ? PHASES.done : PHASES.typing);
  const [typed, setTyped] = useState(reduced ? QUESTION.length : 0);
  const [sources, setSources] = useState(reduced ? SOURCES.length : 0);
  const [streamed, setStreamed] = useState(reduced ? ANSWER.length : 0);

  useEffect(() => {
    if (reduced || !inView) return undefined;

    let cancelled = false;
    const timers = new Set();
    const wait = (ms) =>
      new Promise((resolve) => {
        const t = setTimeout(resolve, ms);
        timers.add(t);
      });
    const wake = async () => {
      while (document.hidden && !cancelled) await wait(400);
    };

    (async () => {
      while (!cancelled) {
        setPhase(PHASES.typing);
        setTyped(0);
        setSources(0);
        setStreamed(0);

        for (let i = 1; i <= QUESTION.length; i++) {
          if (cancelled) return;
          await wake();
          setTyped(i);
          await wait(26 + Math.random() * 26);
        }
        await wait(420);
        if (cancelled) return;

        setPhase(PHASES.retrieving);
        for (let s = 1; s <= SOURCES.length; s++) {
          if (cancelled) return;
          await wake();
          setSources(s);
          await wait(460);
        }
        await wait(560);
        if (cancelled) return;

        setPhase(PHASES.streaming);
        for (let w = 1; w <= ANSWER.length; w++) {
          if (cancelled) return;
          await wake();
          setStreamed(w);
          await wait(42 + Math.random() * 46);
        }

        setPhase(PHASES.done);
        await wait(8200);
        if (cancelled) return;

        setPhase(PHASES.reset);
        await wait(760);
      }
    })();

    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
    };
  }, [inView, reduced, runKey]);

  const streaming = phase === PHASES.streaming;
  const answered = phase === PHASES.done;
  const showAnswer = streamed > 0 || streaming || answered;

  return (
    <Section
      id="product"
      eyebrow="Product"
      title={
        <>
          Ask. Retrieve. Reason. <em>Answer.</em>
        </>
      }
      lead="Every FinSyntra response is composed live: your question is matched against your organization's indexed documents, and the answer streams in — with its sources attached."
    >
      <div ref={sectionRef}>
        <Reveal>
          <div className={`demo ${phase === PHASES.reset ? "demo--reset" : ""}`}>
            <div className="demo__console glass-deep">
              {/* -------- Chat pane -------- */}
              <div className="demo__chat">
                <header className="demo__chat-head">
                  <span className="demo__workspace">
                    <span className="dot dot--pulse" aria-hidden="true" />
                    Finance workspace
                  </span>
                  <span className="demo__preview-tag mono">preview</span>
                </header>

                <div className="demo__thread" aria-live="polite">
                  <div className="demo__msg demo__msg--user">
                    <span className="demo__msg-role mono">You</span>
                    <p>
                      {QUESTION.slice(0, typed)}
                      {phase === PHASES.typing && <span className="demo__caret" aria-hidden="true" />}
                    </p>
                  </div>

                  {phase === PHASES.retrieving && (
                    <div className="demo__status mono">
                      <span className="demo__spinner" aria-hidden="true" />
                      retrieving context · matching passages
                    </div>
                  )}

                  {showAnswer && (
                    <div className="demo__msg demo__msg--ai">
                      <span className="demo__msg-role demo__msg-role--ai mono">FinSyntra</span>
                      <p>
                        {ANSWER.slice(0, streamed).map((tok, i) => {
                          if (tok.c !== undefined) {
                            return (
                              <sup key={i} className="demo__cite">
                                {tok.c}
                              </sup>
                            );
                          }
                          return (
                            <span key={i} className={tok.b ? "demo__figure" : undefined}>
                              {tok.t}{" "}
                            </span>
                          );
                        })}
                        {streaming && <span className="demo__caret" aria-hidden="true" />}
                      </p>

                      {answered && (
                        <footer className="demo__msg-actions">
                          <span className="demo__exports mono">Export:</span>
                          {["PDF", "JSON", "MD"].map((f) => (
                            <span key={f} className="demo__export-chip mono">
                              {f}
                            </span>
                          ))}
                        </footer>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* -------- Sources pane -------- */}
              <aside className="demo__sources" aria-label="Retrieved sources">
                <h3 className="demo__sources-title mono">retrieved context</h3>

                <ul className="demo__source-list">
                  {SOURCES.map((s, i) => {
                    const shown = i < sources;
                    return (
                      <li key={s.name} className={`demo__source demo__source--${s.hue} ${shown ? "is-shown" : ""}`} aria-hidden={!shown}>
                        <span className="demo__source-type mono">{s.type}</span>
                        <span className="demo__source-name">{s.name}</span>
                        <span className="demo__relevance">
                          <span className="demo__relevance-track" aria-hidden="true">
                            <span className="demo__relevance-fill" style={{ "--w": `${s.score}%` }} />
                          </span>
                          <span className="demo__relevance-score mono">{shown ? `${s.score}%` : "—"}</span>
                        </span>
                      </li>
                    );
                  })}
                </ul>

                <div className={`demo__memory ${answered ? "is-shown" : ""}`}>
                  <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                    <path d="M3 5.5 A5 5 0 1 1 2.4 9" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    <path d="M2.2 4.2 L2.4 6.4 L4.5 5.9" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  conversation memory · 4 turns held
                </div>
              </aside>
            </div>

            <div className="demo__foot">
              <p className="mono">Live product preview — illustrative conversation on demo data.</p>
              <button
                type="button"
                className="demo__replay"
                onClick={() => setRunKey((k) => k + 1)}
              >
                <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                  <path d="M3 8 a5 5 0 1 0 1.5 -3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  <path d="M3 2.6 V5 H5.4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Replay
              </button>
            </div>
          </div>
        </Reveal>
      </div>
    </Section>
  );
}
