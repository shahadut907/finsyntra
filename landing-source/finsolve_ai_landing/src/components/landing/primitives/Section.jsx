import Reveal from "./Reveal";
import "./Section.css";

/**
 * Standard narrative section: eyebrow → title → lead, then content.
 * Keeps the page's rhythm consistent without making every block identical.
 */
export default function Section({ id, eyebrow, title, lead, align = "left", children, className = "", labelledBy }) {
  const headingId = labelledBy ?? (id ? `${id}-title` : undefined);

  return (
    <section id={id} className={`section ${className}`} aria-labelledby={headingId}>
      <div className="container">
        <header className={`section__head section__head--${align}`}>
          {eyebrow && (
            <Reveal>
              <p className="eyebrow">{eyebrow}</p>
            </Reveal>
          )}
          {title && (
            <Reveal delay={0.08}>
              <h2 id={headingId} className="display display-lg section__title">
                {title}
              </h2>
            </Reveal>
          )}
          {lead && (
            <Reveal delay={0.16}>
              <p className="lead section__lead">{lead}</p>
            </Reveal>
          )}
        </header>
        {children}
      </div>
    </section>
  );
}
