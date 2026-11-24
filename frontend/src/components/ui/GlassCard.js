import React from 'react';
import { cn } from '../../lib/utils';

/**
 * Flat translucent surface (L2 in glass.css). It deliberately has no motion:
 * previously this wrapped framer-motion with `whileHover={{ scale: 1.02,
 * y: -2 }}` by default, which made every chat message grow and shift under the
 * pointer. Interactive cards only recolor on hover.
 */
export const GlassCard = ({
  children,
  className,
  onClick,
  as: Component = 'div',
  hover: _legacyHover, // accepted for backwards compatibility; hover never moves the card
  ...props
}) => (
  <Component
    onClick={onClick}
    className={cn('fs-card', onClick && 'fs-card--interactive', className)}
    {...props}
  >
    {children}
  </Component>
);

export default GlassCard;
