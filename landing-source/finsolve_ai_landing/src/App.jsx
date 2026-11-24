import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import Atmosphere from "./components/landing/Atmosphere/Atmosphere";
import LandingPage from "./components/landing/LandingPage";
import "./App.css";

/** Restores scroll position on route change (no persisted scroll state). */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

/**
 * Shell for the public marketing surface. Application modules (auth,
 * dashboard) render through their own routes in main.jsx and are unaffected.
 */
export default function App() {
  return (
    <>
      <ScrollToTop />
      <Atmosphere />
      <LandingPage />
    </>
  );
}
