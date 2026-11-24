import Navbar from "./Navbar/Navbar";
import Hero from "./Hero/Hero";
import ProductDemo from "./ProductDemo/ProductDemo";
import Pipeline from "./Pipeline/Pipeline";
import Capabilities from "./Capabilities/Capabilities";
import Security from "./Security/Security";
import Roles from "./Roles/Roles";
import Multilingual from "./Multilingual/Multilingual";
import AdminPreview from "./AdminPreview/AdminPreview";
import TechStack from "./TechStack/TechStack";
import FinalCTA from "./FinalCTA/FinalCTA";
import Footer from "./Footer/Footer";

/**
 * The public marketing surface. Sections follow the product narrative:
 * what it is → see it work → how it works → what it does → how it's
 * protected → who it serves → languages → operations → architecture → enter.
 */
export default function LandingPage() {
  return (
    <>
      <a href="#product" className="skip-link">
        Skip to content
      </a>
      <Navbar />
      <main id="main">
        <Hero />
        <ProductDemo />
        <Pipeline />
        <Capabilities />
        <Security />
        <Roles />
        <Multilingual />
        <AdminPreview />
        <TechStack />
        <FinalCTA />
      </main>
      <Footer />
    </>
  );
}
