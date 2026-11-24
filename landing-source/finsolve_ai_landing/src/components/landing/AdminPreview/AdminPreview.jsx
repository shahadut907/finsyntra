import { useEffect, useState } from "react";
import Section from "../primitives/Section";
import Reveal from "../primitives/Reveal";
import useInView from "../../../hooks/useInView";
import useReducedMotion from "../../../hooks/useReducedMotion";
import "./AdminPreview.css";

const METRICS = [
  { label: "documents indexed", value: 1284, format: "int", suffix: "" },
  { label: "active users", value: 96, format: "int", suffix: "" },
  { label: "queries today", value: 412, format: "int", suffix: "" },
  { label: "avg. retrieval", value: 240, format: "int", suffix: "ms" },
];

const INDEXING = [
  { name: "Q3 Financial Report.pdf", state: "indexed", meta: "214 chunks" },
  { name: "Compliance 2026.docx", state: "indexing", meta: "67%", progress: 67 },
  { name: "Ledger.csv", state: "indexed", meta: "87 chunks" },
];

const ACTIVITY = [
  "s.chowdhury granted Finance role",
  "Annual Report.pdf indexed · 312 chunks",
  "Export generated · PDF",
  "New user invited · HR role",
];

function formatNumber(n) {
  return n.toLocaleString("en-US");
}

/** Count-up when the metric row scrolls into view. */
function Metric({ label, value, suffix, animate }) {
  const [display, setDisplay] = useState(animate ? 0 : value);

  useEffect(() => {
    if (!animate) return undefined;
    let raf;
    const start = performance.now();
    const dur = 1400;
    const tick = (now) => {
      const t = Math.min((now - start) / dur, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(Math.round(value * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [animate, value]);

  return (
    <div className="admin__metric">
      <span className="admin__metric-value mono">
        {formatNumber(display)}
        <em>{suffix}</em>
      </span>
      <span className="admin__metric-label mono">{label}</span>
    </div>
  );
}

/**
 * The operational layer — a compact admin dashboard preview. Deliberately
 * secondary to the AI story: it shows FinSyntra is operable, not just clever.
 */
export default function AdminPreview() {
  const [sectionRef, inView] = useInView({ threshold: 0.3 });
  const reduced = useReducedMotion();
  const [activity, setActivity] = useState(ACTIVITY);

  // Activity feed rotates only while visible
  useEffect(() => {
    if (reduced || !inView) return undefined;
    const id = setInterval(() => {
      if (document.hidden) return;
      setActivity((rows) => [...rows.slice(1), rows[0]]);
    }, 3200);
    return () => clearInterval(id);
  }, [inView, reduced]);

  return (
    <Section
      id="admin"
      eyebrow="Operations"
      title={
        <>
          Intelligence you can <em>operate.</em>
        </>
      }
      lead="Behind the chat surface sits a full administrative layer — users, roles, documents, indexing, and live system metrics."
      align="center"
    >
      <div ref={sectionRef}>
        <Reveal>
          <div className="admin glass-deep">
            <header className="admin__head">
              <span className="admin__title mono">admin · workspace console</span>
              <span className="pill">
                <span className="dot dot--pulse" aria-hidden="true" />
                all systems nominal
              </span>
            </header>

            <div className="admin__metrics">
              {METRICS.map((m) => (
                <Metric key={m.label} label={m.label} value={m.value} suffix={m.suffix} animate={inView && !reduced} />
              ))}
            </div>

            <div className="admin__panes">
              <div className="admin__pane">
                <h3 className="admin__pane-title mono">indexing state</h3>
                <ul className="admin__index-list">
                  {INDEXING.map((d) => (
                    <li key={d.name} className="admin__index-row">
                      <span className="admin__index-name mono">{d.name}</span>
                      {d.state === "indexed" ? (
                        <span className="admin__state admin__state--done mono">indexed · {d.meta}</span>
                      ) : (
                        <span className="admin__state admin__state--wip">
                          <span className="admin__state-track" aria-hidden="true">
                            <span className="admin__state-fill" style={{ "--w": `${d.progress}%` }} />
                          </span>
                          <span className="mono">{d.meta}</span>
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="admin__pane">
                <h3 className="admin__pane-title mono">recent activity</h3>
                <div className="admin__feed-window">
                  <ul className="admin__feed" key={activity[0]}>
                    {activity.map((a) => (
                      <li key={a} className="admin__feed-row">
                        <span className="admin__feed-dot" aria-hidden="true" />
                        <span className="mono">{a}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>

            <p className="admin__note mono">preview data — the console ships with the application</p>
          </div>
        </Reveal>
      </div>
    </Section>
  );
}
