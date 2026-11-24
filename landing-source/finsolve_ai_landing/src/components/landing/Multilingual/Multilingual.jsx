import { useEffect, useRef, useState } from "react";
import Section from "../primitives/Section";
import Reveal from "../primitives/Reveal";
import useInView from "../../../hooks/useInView";
import useReducedMotion from "../../../hooks/useReducedMotion";
import "./Multilingual.css";

const CONVERSATIONS = {
  en: {
    lang: "en",
    toggleLabel: "English",
    question: "Summarize our Q2 revenue performance.",
    answer:
      "Q2 revenue grew 12.4% quarter-over-quarter, led by recurring enterprise contracts (+18%). Gross margin held steady at 61%.",
    source: "Q2 Financial Report.pdf",
  },
  bn: {
    lang: "bn",
    toggleLabel: "বাংলা",
    question: "গত ত্রৈমাসিকের ব্যয়ের প্রধান পরিবর্তনগুলো দেখাও।",
    answer:
      "গত ত্রৈমাসিকে মোট ব্যয় ৮.৪% বেড়েছে। প্রধান পরিবর্তন: বিপণন খাতে ২৩% বৃদ্ধি, অফিস ভাড়ায় ৪% হ্রাস, এবং নতুন নিয়োগের কারণে বেতন খাতে ১১% প্রবৃদ্ধি।",
    source: "ত্রৈমাসিক আর্থিক প্রতিবেদন",
  },
};

/**
 * Bilingual demonstration — a single console that alternates between an
 * English and a Bangla conversation. The toggle auto-alternates while the
 * section is visible; user interaction takes over.
 */
export default function Multilingual() {
  const [sectionRef, inView] = useInView({ threshold: 0.35 });
  const reduced = useReducedMotion();
  const [lang, setLang] = useState("en");
  const userTouched = useRef(false);

  useEffect(() => {
    if (reduced || !inView || userTouched.current) return undefined;
    const id = setInterval(() => {
      if (!document.hidden) setLang((l) => (l === "en" ? "bn" : "en"));
    }, 7000);
    return () => clearInterval(id);
  }, [inView, reduced]);

  const c = CONVERSATIONS[lang];
  const isBn = lang === "bn";

  return (
    <Section
      id="multilingual"
      eyebrow="Multilingual"
      title={
        <>
          Fluent in English — <span className="bn text-gradient">এবং বাংলায়।</span>
        </>
      }
      lead="Organizations don't operate in one language. FinSyntra understands questions and reasons over documents in both English and Bangla — with proper rendering, digits, and typography."
    >
      <div ref={sectionRef} className="multi">
        <Reveal className="multi__copy">
          <p>
            The same retrieval pipeline, the same grounding, the same streaming answers — in whichever
            language your team thinks in. Bengali text, including numerals, is rendered with a dedicated
            typeface so every glyph stays crisp.
          </p>
          <ul className="multi__points">
            <li>
              <span className="mono">01</span>
              Ask in either language — intent carries across follow-ups
            </li>
            <li>
              <span className="mono">02</span>
              Documents indexed per tenant, regardless of language
            </li>
            <li>
              <span className="mono">03</span>
              Exports preserve language and layout
            </li>
          </ul>
        </Reveal>

        <Reveal delay={0.12} className="multi__console-wrap">
          <div className="multi__console glass-deep">
            <div className="multi__switch" role="group" aria-label="Preview language">
              {Object.entries(CONVERSATIONS).map(([key, conv]) => (
                <button
                  key={key}
                  type="button"
                  className={`multi__switch-btn ${lang === key ? "is-active" : ""} ${key === "bn" ? "bn" : "mono"}`}
                  aria-pressed={lang === key}
                  lang={conv.lang}
                  onClick={() => {
                    userTouched.current = true;
                    setLang(key);
                  }}
                >
                  {conv.toggleLabel}
                </button>
              ))}
            </div>

            <div className="multi__thread" key={lang}>
              <div className="multi__msg multi__msg--user">
                <p className={isBn ? "bn" : undefined} lang={c.lang}>
                  {c.question}
                </p>
              </div>
              <div className="multi__msg multi__msg--ai">
                <span className="mono multi__role">FinSyntra</span>
                <p className={isBn ? "bn" : undefined} lang={c.lang}>
                  {c.answer}
                </p>
                <span className={`multi__source mono ${isBn ? "bn" : ""}`} lang={c.lang}>
                  ⌁ {c.source}
                </span>
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </Section>
  );
}
