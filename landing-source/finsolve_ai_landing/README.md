# FinSyntra AI — Landing Page

Premium public marketing surface for **FinSyntra AI**, a RAG-powered financial
intelligence platform. Liquid-glass design system, animated product
storytelling, zero animation dependencies.

## Run

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # production bundle → dist/
```

## Structure

```text
src/
  main.jsx                  # Router: / · /login · /register · /dashboard
  App.jsx                   # Landing shell + scroll restore
  styles/                   # tokens · base · glass (design system)
  hooks/                    # useInView · useReducedMotion
  components/
    app/Stub.jsx            # Branded mount-point stubs for real app routes
    landing/
      LandingPage.jsx       # Section narrative assembly
      Atmosphere/           # Fixed aurora + grid background
      Navbar/  Hero/        # Floating glass nav · cinematic hero + RAG flow
      ProductDemo/          # Auto-playing Ask→Retrieve→Reason→Answer console
      Pipeline/             # 6-stage RAG stepper (Upload→…→Answer)
      Capabilities/         # Asymmetric bento grid
      Security/             # Tenant isolation vaults
      Roles/                # Interactive role-based intelligence tabs
      Multilingual/         # EN / বাংলা console
      AdminPreview/         # Operational dashboard preview
      TechStack/            # Architecture strip
      FinalCTA/  Footer/
      primitives/           # Brand · CTAButton · Reveal · Section
```

## Integrating into the full FinSyntra application

This page is a **presentation layer only** — it makes no API calls and touches
no auth state. To mount it inside the existing product frontend:

1. Copy `src/components/landing/`, `src/hooks/`, and `src/styles/` into the app.
2. Import the three stylesheets once (order matters: tokens → base → glass).
3. Register `<LandingPage />` on the public `/` route — the existing
   `/login`, `/register`, and `/dashboard` routes stay exactly as they are.
   Delete `src/components/app/Stub.jsx`; it only exists so the CTAs in this
   standalone build route to real destinations.
4. Nothing else changes: JWT/httpOnly-cookie auth, RBAC routing, SSE chat,
   and tenant isolation are untouched by this layer.
