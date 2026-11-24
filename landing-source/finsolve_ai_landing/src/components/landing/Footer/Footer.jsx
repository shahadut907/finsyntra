import Brand from "../primitives/Brand";
import { APP_LOGIN_URL } from "../../../appUrl";
import "./Footer.css";

const COLUMNS = [
  {
    title: "Product",
    links: [
      { label: "AI Financial Chat", href: "#product" },
      { label: "RAG Pipeline", href: "#intelligence" },
      { label: "Capabilities", href: "#platform" },
      { label: "Admin Layer", href: "#admin" },
    ],
  },
  {
    title: "Platform",
    links: [
      { label: "Architecture", href: "#stack" },
      { label: "Multilingual", href: "#multilingual" },
      { label: "Roles & Access", href: "#roles" },
      { label: "Exports", href: "#platform" },
    ],
  },
  {
    title: "Security",
    links: [
      { label: "Tenant Isolation", href: "#security" },
      { label: "RBAC", href: "#roles" },
      { label: "Authentication", href: "#security" },
    ],
  },
  {
    title: "Account",
    links: [
      { label: "Sign In", href: APP_LOGIN_URL },
      { label: "Open Dashboard", href: "/app" },
    ],
  },
];

/** Minimal premium footer — only real anchors and application routes. */
export default function Footer() {
  return (
    <footer className="footer">
      <div className="container">
        <div className="footer__top">
          <div className="footer__brand">
            <Brand />
            <p className="footer__tagline">
              Financial intelligence, grounded in your organization&apos;s knowledge — retrieval-augmented, tenant-isolated, bilingual.
            </p>
            <p className="footer__stack mono">
              React · FastAPI · ChromaDB · Ollama · SSE
            </p>
          </div>

          {COLUMNS.map((col) => (
            <nav key={col.title} className="footer__col" aria-label={col.title}>
              <h3 className="footer__col-title">{col.title}</h3>
              <ul>
                {col.links.map((l) => (
                  <li key={l.label}>
                    <a href={l.href}>{l.label}</a>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        <div className="footer__bottom">
          <p>© {new Date().getFullYear()} FinSyntra AI — internal deployment.</p>
          <p className="mono footer__note">Answers are grounded in indexed organizational documents only.</p>
        </div>
      </div>
    </footer>
  );
}
