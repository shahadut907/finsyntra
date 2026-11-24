/**
 * Readable plain-text rendering of the small LaTeX subset models put in
 * answers ("\( \frac{840,000}{3,200,000} = 0.2625 \)"). The result is plain
 * text (rendered as a React text node), so no markup is ever produced.
 */

const SYMBOLS = [
  [/\\times/g, '×'],
  [/\\div/g, '÷'],
  [/\\cdot/g, '·'],
  [/\\approx/g, '≈'],
  [/\\(?:leq|le)\b/g, '≤'],
  [/\\(?:geq|ge)\b/g, '≥'],
  [/\\(?:neq|ne)\b/g, '≠'],
  [/\\pm/g, '±'],
  [/\\to|\\rightarrow/g, '→'],
  [/\\infty/g, '∞'],
  [/\\sum/g, 'Σ'],
  [/\\%/g, '%'],
  [/\\\$/g, '$'],
  [/\\[,;:! ]/g, ' '],
  [/\\(?:quad|qquad)\b/g, ' '],
  [/\\left|\\right/g, '']
];

// Innermost braces only, so nested fractions resolve from the inside out.
const FRAC = /\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/;
const TEXT = /\\(?:text|mathrm|mathbf|textbf|operatorname)\s*\{([^{}]*)\}/;
const SQRT = /\\sqrt\s*\{([^{}]*)\}/;

const wrap = (term) => {
  const t = term.trim();
  return /^[\w.,%৳০-৯]+$/u.test(t) ? t : `(${t})`;
};

export function formatMath(source) {
  let text = String(source ?? '');
  for (let guard = 0; guard < 20; guard += 1) {
    const before = text;
    text = text
      .replace(TEXT, (_, inner) => inner)
      .replace(FRAC, (_, num, den) => `${wrap(num)} / ${wrap(den)}`)
      .replace(SQRT, (_, inner) => `√${wrap(inner)}`);
    if (text === before) break;
  }
  SYMBOLS.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement);
  });
  return text
    .replace(/\^\{([^{}]*)\}/g, '^$1')
    .replace(/_\{([^{}]*)\}/g, '_$1')
    .replace(/[{}]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export default formatMath;
