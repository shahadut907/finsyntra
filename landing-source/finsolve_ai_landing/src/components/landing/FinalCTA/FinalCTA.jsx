import Reveal from "../primitives/Reveal";
import CTAButton from "../primitives/CTAButton";
import { APP_LOGIN_URL } from "../../../appUrl";
import "./FinalCTA.css";

/**
 * Closing statement — a spectral horizon with the primary entry
 * points into the real application.
 */
export default function FinalCTA() {
  return (
    <section className="final" aria-labelledby="final-title">
      <div className="final__atmosphere" aria-hidden="true">
        <span className="final__horizon" />
        <span className="final__glow" />
      </div>

      <div className="container final__inner">
        <Reveal>
          <p className="eyebrow final__eyebrow">Begin</p>
        </Reveal>
        <Reveal delay={0.08}>
          <h2 id="final-title" className="display display-xl final__title">
            Turn organizational knowledge
            <br />
            into <em className="text-gradient">intelligence.</em>
          </h2>
        </Reveal>
        <Reveal delay={0.16}>
          <p className="lead final__lead">
            Your documents already hold the answers. FinSyntra makes them conversational — securely,
            bilingually, and in real time.
          </p>
        </Reveal>
        <Reveal delay={0.24}>
          <div className="final__ctas">
            <CTAButton href={APP_LOGIN_URL} size="lg">
              Enter FinSyntra
              <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
                <path d="M3 8 h10 M9 4 l4 4 -4 4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </CTAButton>
            <CTAButton href={APP_LOGIN_URL} variant="ghost" size="lg" magnetic={false}>
              Sign In
            </CTAButton>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
