import React from 'react';
import { cn } from '../../lib/utils';
import { cva } from 'class-variance-authority';

const inputVariants = cva(
  'flex w-full rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-ring disabled:cursor-not-allowed disabled:opacity-50',
  {
    variants: {
      variant: {
        default: '',
        filled: 'bg-muted border-0',
        ghost: 'border-0 bg-transparent',
      },
      size: {
        sm: 'h-9 px-2 text-xs',
        default: 'h-10 px-3',
        lg: 'h-11 px-4',
        xl: 'h-12 px-4 text-base',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

export const Input = React.forwardRef(({
  className,
  variant,
  size,
  type = 'text',
  ...props
}, ref) => {
  return (
    <input
      type={type}
      className={cn(inputVariants({ variant, size, className }))}
      ref={ref}
      {...props}
    />
  );
});

export const Textarea = React.forwardRef(({
  className,
  variant,
  ...props
}, ref) => {
  return (
    <textarea
      className={cn(
        'flex min-h-[80px] w-full rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-ring disabled:cursor-not-allowed disabled:opacity-50',
        variant === 'filled' && 'bg-muted border-0',
        variant === 'ghost' && 'border-0 bg-transparent',
        className
      )}
      ref={ref}
      {...props}
    />
  );
});

export const Label = React.forwardRef(({
  className,
  ...props
}, ref) => (
  <label
    ref={ref}
    className={cn(
      'text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70',
      className
    )}
    {...props}
  />
));

Input.displayName = 'Input';
Textarea.displayName = 'Textarea';
Label.displayName = 'Label';
