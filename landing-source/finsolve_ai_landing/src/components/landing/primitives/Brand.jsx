import { Link } from "react-router-dom";
import "./Brand.css";

/** FinSyntra brand mark: a glass ring with an ascending data line. */
export default function Brand({ to = "/", size = "md", withWord = true }) {
  return (
    <Link to={to} className={`brand brand--${size}`} aria-label="FinSyntra AI — home">
      <span className="brand__mark" aria-hidden="true">
        <svg viewBox="0 0 64 64" width="30" height="30">
          <defs>
            <linearGradient id="brand-g" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#60a5fa" />
              <stop offset="0.5" stopColor="#a78bfa" />
              <stop offset="1" stopColor="#34d3c2" />
            </linearGradient>
          </defs>
          <circle cx="32" cy="32" r="26" fill="none" stroke="url(#brand-g)" strokeWidth="5" opacity="0.9" />
          <path d="M18 40 L28 27 L36 35 L46 20" fill="none" stroke="url(#brand-g)" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      {withWord && (
        <span className="brand__word">
          FinSyntra
          <span className="brand__ai">AI</span>
        </span>
      )}
    </Link>
  );
}
