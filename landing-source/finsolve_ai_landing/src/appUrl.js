// Entry URL of the main FinSyntra app (the demo login lives at /app/login).
//
// Production serves the landing and the app on ONE domain (/ -> landing,
// /app -> app), so the relative default is correct there.
// Local development runs the app on a separate port — set VITE_APP_URL in
// .env.development (e.g. http://localhost:3002/app/login). Never hard-code a
// dev origin here; the fallback must stay production-safe.
export const APP_LOGIN_URL = import.meta.env.VITE_APP_URL || "/app/login";

// "Try Demo" entry: same login page, flagged so it can explain itself when the
// demo panel is not enabled in that build (see LoginForm.js demoRequested).
export const APP_DEMO_URL = `${APP_LOGIN_URL}${APP_LOGIN_URL.includes("?") ? "&" : "?"}demo=1`;
