import { Link } from "react-router-dom";
import { useRef } from "react";
import useReducedMotion from "../../../hooks/useReducedMotion";
import "./CTAButton.css";

/**
 * FinSyntra CTA system.
 *  - primary: spectral gradient fill with a slow internal shimmer; gently
 *    magnetizes toward the cursor (disabled for reduced motion / touch).
 *  - ghost: glass surface with spectral edge on hover.
 * Renders a router Link, plain anchor, or button depending on props.
 */
export default function CTAButton({
  to,
  href,
  onClick,
  type = "button",
  variant = "primary",
  size = "md",
  magnetic = true,
  className = "",
  children,
  ...rest
}) {
  const ref = useRef(null);
  const reduced = useReducedMotion();

  const handleMove = (e) => {
    if (!magnetic || reduced || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const x = (e.clientX - rect.left - rect.width / 2) / (rect.width / 2);
    const y = (e.clientY - rect.top - rect.height / 2) / (rect.height / 2);
    ref.current.style.transform = `translate(${x * 5}px, ${y * 4}px)`;
  };

  const handleLeave = () => {
    if (ref.current) ref.current.style.transform = "";
  };

  const cls = `cta cta--${variant} cta--${size} ${className}`.trim();

  if (to) {
    return (
      <Link ref={ref} to={to} className={cls} onMouseMove={handleMove} onMouseLeave={handleLeave} {...rest}>
        <span className="cta__label">{children}</span>
      </Link>
    );
  }

  if (href) {
    return (
      <a ref={ref} href={href} className={cls} onMouseMove={handleMove} onMouseLeave={handleLeave} {...rest}>
        <span className="cta__label">{children}</span>
      </a>
    );
  }

  return (
    <button ref={ref} type={type} onClick={onClick} className={cls} onMouseMove={handleMove} onMouseLeave={handleLeave} {...rest}>
      <span className="cta__label">{children}</span>
    </button>
  );
}
