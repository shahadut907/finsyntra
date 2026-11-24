import Section from "../primitives/Section";
import Reveal from "../primitives/Reveal";
import "./Security.css";

const TENANTS = [
  {
    id: "A",
    name: "Tenant A",
    hue: "blue",
    docs: ["Q3 Report.pdf", "Budget.csv"],
  },
  {
    id: "B",
    name: "Tenant B",
    hue: "violet",
    docs: ["Audit 2026.docx", "Ledger.csv"],
  },
  {
    id: "C",
    name: "Tenant C",
    hue: "emerald",
    docs: ["Forecast.md", "Expenses.pdf"],
  },
];

const MECHANISMS = [
  { label: "JWT sessions · httpOnly cookies", icon: "key" },
  { label: "Role-based access control", icon: "shield" },
  { label: "Tenant-scoped retrieval", icon: "scope" },
  { label: "Per-tenant knowledge index", icon: "layers" },
];

function MechanismIcon({ name }) {
  if (name === "key")
    return (
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <circle cx="5.5" cy="10.5" r="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M7.8 8.2 L13.5 2.5 M11 5 L13 7 M9.3 6.7 L10.7 8.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  if (name === "shield")
    return (
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <path d="M8 1.5 L14 4 v4 c0 3 -2.5 5 -6 6.5 C4.5 13 2 11 2 8 V4 Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      </svg>
    );
  if (name === "scope")
    return (
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <circle cx="8" cy="8" r="1.6" fill="currentColor" />
        <path d="M8 1 v2.4 M8 12.6 V15 M1 8 h2.4 M12.6 8 H15" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    );
  return (
    <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
      <path d="M8 1.8 L14 5 v6 L8 14.2 L2 11 V5 Z M2 5 L8 8 L14 5 M8 8 V14.2" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * Security story: authentication + RBAC + hard tenant isolation.
 * The visualization shows three tenant vaults with independent knowledge
 * indexes — and blocked cross-tenant retrieval between them.
 */
export default function Security() {
  return (
    <Section
      id="security"
      eyebrow="Security"
      title={
        <>
          Your knowledge never <em>leaks</em> across boundaries.
        </>
      }
      lead="FinSyntra is multi-tenant by design. Every query, every retrieved passage, and every indexed document is scoped to your organization — enforced at the API, not by convention."
    >
      <div className="security">
        {/* -------- Vaults -------- */}
        <Reveal className="security__vaults-wrap">
          <div className="security__vaults" role="img" aria-label="Three tenant workspaces with isolated knowledge indexes; cross-tenant retrieval is blocked">
            {TENANTS.map((t, i) => (
              <div key={t.id} className={`security__vault security__vault--${t.hue}`} style={{ "--i": i }}>
                <div className="security__vault-head">
                  <span className="security__vault-id mono">{t.name}</span>
                  <span className="security__vault-lock" aria-hidden="true">
                    <svg viewBox="0 0 16 16" width="11" height="11">
                      <rect x="3" y="7.3" width="10" height="6.4" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
                      <path d="M5.4 7.3 V5.1 a2.6 2.6 0 0 1 5.2 0 V7.3" fill="none" stroke="currentColor" strokeWidth="1.4" />
                    </svg>
                    isolated
                  </span>
                </div>
                <ul className="security__vault-docs">
                  {t.docs.map((d) => (
                    <li key={d} className="mono">
                      {d}
                    </li>
                  ))}
                </ul>
                <div className="security__vault-index mono">
                  <span className="security__vault-pulse" aria-hidden="true" />
                  private index
                </div>
                {i < TENANTS.length - 1 && (
                  <span className="security__block" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="16" height="16">
                      <path d="M5 5 L19 19 M19 5 L5 19" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                  </span>
                )}
              </div>
            ))}
          </div>
          <p className="security__caption mono">cross-tenant retrieval · blocked at the API layer</p>
        </Reveal>

        {/* -------- Mechanisms -------- */}
        <Reveal delay={0.12} className="security__mechanisms">
          <ul className="security__list">
            {MECHANISMS.map((m, i) => (
              <li key={m.label} className="security__item glass-lite" style={{ "--i": i }}>
                <span className="security__item-icon" aria-hidden="true">
                  <MechanismIcon name={m.icon} />
                </span>
                <span>{m.label}</span>
              </li>
            ))}
          </ul>
          <p className="security__note">
            Sessions are issued as JWTs and stored in httpOnly cookies with refresh-token rotation;
            document visibility follows each user&apos;s role. See{" "}
            <a href="#roles">how roles shape intelligence</a>.
          </p>
        </Reveal>
      </div>
    </Section>
  );
}
