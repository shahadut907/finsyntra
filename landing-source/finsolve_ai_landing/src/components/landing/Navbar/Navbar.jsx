import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import Brand from "../primitives/Brand";
import CTAButton from "../primitives/CTAButton";
import { APP_LOGIN_URL, APP_DEMO_URL } from "../../../appUrl";
import "./Navbar.css";

const LINKS = [
  { label: "Product", href: "#product" },
  { label: "Intelligence", href: "#intelligence" },
  { label: "Security", href: "#security" },
  { label: "Platform", href: "#platform" },
  { label: "Technology", href: "#stack" },
];

/**
 * Floating glass navigation. Detaches into a compact glass pill once
 * the page scrolls past the hero's upper edge.
 */
export default function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Close the mobile sheet on navigation
  useEffect(() => {
    setOpen(false);
  }, [location]);

  // Lock body scroll while the mobile sheet is open
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <header className={`nav ${scrolled ? "nav--scrolled" : ""}`}>
      <div className="container nav__inner">
        <Brand />

        <nav className="nav__links" aria-label="Primary">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} className="nav__link">
              {l.label}
            </a>
          ))}
        </nav>

        <div className="nav__actions">
          <a href={APP_LOGIN_URL} className="nav__signin">
            Sign In
          </a>
          <CTAButton href={APP_DEMO_URL} className="nav__cta">
            Try Demo
          </CTAButton>
        </div>

        <button
          type="button"
          className={`nav__burger ${open ? "nav__burger--open" : ""}`}
          aria-expanded={open}
          aria-controls="nav-sheet"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((v) => !v)}
        >
          <span />
          <span />
        </button>
      </div>

      <div id="nav-sheet" className={`nav__sheet ${open ? "nav__sheet--open" : ""}`} aria-hidden={!open}>
        <nav className="nav__sheet-links" aria-label="Mobile">
          {LINKS.map((l, i) => (
            <a key={l.href} href={l.href} className="nav__sheet-link" style={{ "--i": i }} onClick={() => setOpen(false)}>
              {l.label}
              <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <path d="M6 3 L11 8 L6 13" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </a>
          ))}
        </nav>
        <div className="nav__sheet-ctas">
          <CTAButton href={APP_DEMO_URL} variant="ghost" magnetic={false}>
            Try Demo
          </CTAButton>
          <CTAButton href={APP_LOGIN_URL} magnetic={false}>
            Sign In
          </CTAButton>
        </div>
      </div>
    </header>
  );
}
