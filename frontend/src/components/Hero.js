import React from 'react';
import { motion } from 'framer-motion';
import CategoryPill from './CategoryPill';
import Logo from './ui/Logo';

export const Hero = ({ user, onCategorySelect }) => {
  const categories = [
    {
      id: 'finance',
      title: 'Finance',
      description: 'Summarize the key figures from the latest quarterly report'
    },
    {
      id: 'hr',
      title: 'HR & Policy',
      description: 'Summarize our leave policy from the HR documents'
    },
    {
      id: 'leadership',
      title: 'Leadership',
      description: 'Give me an executive snapshot of this quarter'
    }
  ];

  // Public-demo identities are named "Demo <Role>" (e.g. "Demo CEO", "Demo
  // Finance Employee") so every persona could greet as "Hey! Demo" — drop a
  // leading "Demo" token so the greeting instead reads "Hey! CEO", "Hey!
  // Finance", etc.
  const nameParts = (user?.name || '').trim().split(/\s+/).filter(Boolean);
  if (nameParts.length > 1 && nameParts[0].toLowerCase() === 'demo') {
    nameParts.shift();
  }
  const firstName = nameParts[0] || 'Raf';

  return (
    <div className="fs-page-scroll">
      <div className="fs-hero">
        {/* Marketing Hero */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4 }}
          className="fs-hero-brand"
        >
          <div className="fs-hero-brand-row">
            <Logo size={40} showText={false} className="fs-logo-tint" />
            <h3>Welcome to FinSyntra</h3>
          </div>
          <p className="fs-hero-lede">Financial intelligence, grounded in your data</p>
          <p className="fs-hero-sub">
            Grounded answers from your own documents — streamed in real time, scoped to your role and tenant
          </p>
        </motion.div>

        {/* Hero Text */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.1 }}
          className="fs-hero-title"
          role="banner"
          aria-label="Welcome message"
        >
          <h2>Hey! {firstName}</h2>
          <p>What can I help with?</p>
        </motion.div>

        {/* Category Pills */}
        <div className="fs-hero-grid" role="region" aria-label="Quick start options">
          {categories.map((category, index) => (
            <CategoryPill
              key={category.id}
              title={category.title}
              description={category.description}
              onClick={() => onCategorySelect(category)}
              delay={0.05 * index}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

export default Hero;
