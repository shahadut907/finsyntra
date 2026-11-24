// Empty on purpose: the landing page uses plain CSS (no Tailwind/PostCSS
// plugins). Without this file, Vite's PostCSS config search walks up to the
// monorepo root and picks up ../../postcss.config.js (Tailwind, for the
// main FinSyntra frontend), which fails to resolve here since this package
// doesn't depend on tailwindcss.
export default {
  plugins: {},
};
