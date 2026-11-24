import React from 'react';
import { cn } from '../../lib/utils';
import { cva } from 'class-variance-authority';

const cardVariants = cva(
  'card',
  {
    variants: {
      variant: {
        default: 'card',
        elevated: 'card card-elevated',
        outline: 'border-2 border-border bg-card text-card-foreground rounded-lg',
        ghost: 'bg-transparent border-0 shadow-none',
        gradient: 'bg-gradient-to-br from-brand/5 to-accent/5 border-brand/20',
      },
      padding: {
        none: 'p-0',
        sm: 'p-4',
        default: 'p-6',
        lg: 'p-8',
        xl: 'p-10',
      },
      hover: {
        none: '',
        lift: 'hover:shadow-elevated hover:-translate-y-0.5 transition-all duration-200',
        glow: 'hover:shadow-high hover:shadow-brand/10 transition-all duration-200',
        scale: 'hover:scale-[1.02] transition-transform duration-200',
      }
    },
    defaultVariants: {
      variant: 'default',
      padding: 'default',
      hover: 'none',
    },
  }
);

export const Card = React.forwardRef(({
  className,
  variant,
  padding,
  hover,
  children,
  ...props
}, ref) => (
  <div
    ref={ref}
    className={cn(cardVariants({ variant, padding, hover, className }))}
    {...props}
  >
    {children}
  </div>
));

export const CardHeader = React.forwardRef(({
  className,
  children,
  ...props
}, ref) => (
  <div
    ref={ref}
    className={cn('flex flex-col space-y-1.5 pb-6', className)}
    {...props}
  >
    {children}
  </div>
));

export const CardTitle = React.forwardRef(({
  className,
  children,
  ...props
}, ref) => (
  <h3
    ref={ref}
    className={cn('text-2xl font-semibold leading-none tracking-tight', className)}
    {...props}
  >
    {children}
  </h3>
));

export const CardDescription = React.forwardRef(({
  className,
  children,
  ...props
}, ref) => (
  <p
    ref={ref}
    className={cn('text-sm text-muted-foreground', className)}
    {...props}
  >
    {children}
  </p>
));

export const CardContent = React.forwardRef(({
  className,
  children,
  ...props
}, ref) => (
  <div
    ref={ref}
    className={cn('pt-0', className)}
    {...props}
  >
    {children}
  </div>
));

export const CardFooter = React.forwardRef(({
  className,
  children,
  ...props
}, ref) => (
  <div
    ref={ref}
    className={cn('flex items-center pt-6', className)}
    {...props}
  >
    {children}
  </div>
));

Card.displayName = 'Card';
CardHeader.displayName = 'CardHeader';
CardTitle.displayName = 'CardTitle';
CardDescription.displayName = 'CardDescription';
CardContent.displayName = 'CardContent';
CardFooter.displayName = 'CardFooter';
