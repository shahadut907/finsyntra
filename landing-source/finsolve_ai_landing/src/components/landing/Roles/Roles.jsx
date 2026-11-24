import { useRef, useState } from "react";
import Section from "../primitives/Section";
import Reveal from "../primitives/Reveal";
import "./Roles.css";

const ROLES = [
  {
    key: "finance",
    label: "Finance",
    title: "Finance teams interrogate the numbers.",
    desc: "Budgets, ledgers, expense reports — finance asks precise questions and gets precise, source-linked figures back.",
    ask: "Which cost centers exceeded allocation this quarter?",
    docs: ["Department Budget.csv", "Q3 Financial Report.pdf", "Ledger.csv"],
    scope: 82,
  },
  {
    key: "management",
    label: "Management",
    title: "Managers see the shape of performance.",
    desc: "Summaries and comparisons across departments, without digging through documents line by line.",
    ask: "Give me a one-page summary of quarterly performance.",
    docs: ["Q3 Financial Report.pdf", "KPI Dashboard.md"],
    scope: 64,
  },
  {
    key: "hr",
    label: "HR",
    title: "HR grounds policy in the actual policy.",
    desc: "Headcount, hiring status, and policy questions answered from HR's own indexed documents.",
    ask: "Summarize hiring progress against the quarterly plan.",
    docs: ["Hiring Plan.xlsx.csv", "HR Policy.docx"],
    scope: 48,
  },
  {
    key: "engineering",
    label: "Engineering",
    title: "Engineering traces technical spend.",
    desc: "Infrastructure costs and technical documentation, reasoned over the engineering team's corpus.",
    ask: "What drove the infrastructure cost increase?",
    docs: ["Infra Costs.csv", "Tech Review.md"],
    scope: 56,
  },
  {
    key: "executive",
    label: "Executive",
    title: "Executives get the board-level view.",
    desc: "Margins, trajectories, and risk — composed from the organization's consolidated reporting.",
    ask: "How did margins trend across the year?",
    docs: ["Annual Report.pdf", "Board Deck.docx", "Forecast.md"],
    scope: 71,
  },
  {
    key: "admin",
    label: "Admin",
    title: "Admins operate the intelligence layer.",
    desc: "Full operational control — users, roles, documents, indexing, and system metrics — beyond asking questions.",
    ask: "Reindex the newly uploaded compliance documents.",
    docs: ["All tenant documents", "System metrics", "Activity log"],
    scope: 100,
  },
];

/**
 * Role-based intelligence, told interactively: pick a role, see the
 * questions that role asks, the documents in its scope, and how much of
 * the tenant's knowledge it can reach.
 */
export default function Roles() {
  const [active, setActive] = useState(0);
  const tabRefs = useRef([]);
  const role = ROLES[active];

  const onKeyDown = (e) => {
    let next = null;
    if (e.key === "ArrowRight") next = (active + 1) % ROLES.length;
    if (e.key === "ArrowLeft") next = (active - 1 + ROLES.length) % ROLES.length;
    if (e.key === "Home") next = 0;
    if (e.key === "End") next = ROLES.length - 1;
    if (next !== null) {
      e.preventDefault();
      setActive(next);
      tabRefs.current[next]?.focus();
    }
  };

  return (
    <Section
      id="roles"
      eyebrow="Access"
      title={
        <>
          The right intelligence <em>for every role.</em>
        </>
      }
      lead="Access isn't a wall — it's a lens. Each role sees the documents, and receives the answers, appropriate to its responsibility."
    >
      <Reveal>
        <div className="roles">
          <div className="roles__tabs" role="tablist" aria-label="Organizational roles" onKeyDown={onKeyDown}>
            {ROLES.map((r, i) => (
              <button
                key={r.key}
                ref={(el) => (tabRefs.current[i] = el)}
                type="button"
                role="tab"
                id={`role-tab-${r.key}`}
                aria-selected={i === active}
                aria-controls={`role-panel-${r.key}`}
                tabIndex={i === active ? 0 : -1}
                className={`roles__tab ${i === active ? "is-active" : ""}`}
                onClick={() => setActive(i)}
              >
                {r.label}
              </button>
            ))}
          </div>

          <div
            className="roles__panel glass"
            role="tabpanel"
            id={`role-panel-${role.key}`}
            aria-labelledby={`role-tab-${role.key}`}
            key={role.key}
          >
            <div className="roles__panel-main">
              <h3 className="roles__panel-title display display-md">{role.title}</h3>
              <p className="roles__panel-desc">{role.desc}</p>
              <div className="roles__ask">
                <span className="mono roles__ask-label">typically asks</span>
                <p className="roles__ask-text">“{role.ask}”</p>
              </div>
            </div>

            <div className="roles__panel-side">
              <span className="mono roles__docs-label">documents in scope</span>
              <ul className="roles__docs">
                {role.docs.map((d) => (
                  <li key={d} className="mono">
                    {d}
                  </li>
                ))}
              </ul>
              <div className="roles__scope">
                <span className="mono roles__scope-label">knowledge reach</span>
                <span className="roles__scope-track" aria-hidden="true">
                  <span className="roles__scope-fill" style={{ "--w": `${role.scope}%` }} />
                </span>
                <span className="mono roles__scope-value">{role.scope}%</span>
              </div>
            </div>
          </div>
        </div>
      </Reveal>
    </Section>
  );
}
