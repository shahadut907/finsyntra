import React from 'react';
import { motion } from 'framer-motion';
import GlassCard from './ui/GlassCard';

// Entrance fade only: no hover/tap scale, so the tile never changes size or
// position while the pointer is on it (hover only recolors the surface).
export const CategoryPill = ({
  title,
  description,
  onClick,
  delay = 0
}) => {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3, delay }}
    >
      <GlassCard
        as="button"
        type="button"
        onClick={onClick}
        className="fs-pill"
        aria-label={`${title}: ${description}`}
      >
        <span className="fs-pill-title">{title}</span>
        <span className="fs-pill-desc">{description}</span>
      </GlassCard>
    </motion.div>
  );
};

export default CategoryPill;
