import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import App from "./App";
import "./styles/index.css";

/**
 * The real application (auth, dashboard) is a separate build served at
 * /app by Nginx — see deploy/production/nginx.conf. This SPA only owns
 * the marketing surface, so every path renders the same landing page.
 */
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="*" element={<App />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>
);
