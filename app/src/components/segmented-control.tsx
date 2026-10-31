import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  description?: ReactNode;
}

/** One choice out of a few, shown side by side (a radio group). With descriptions, each option
 *  is a small card; without, a compact pill row. Wraps onto more rows on narrow screens. */
export function SegmentedControl<T extends string>({ options, value, onChange, disabled, label, className }: {
  options: readonly SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  label: string;
  className?: string;
}) {
  const cards = options.some((o) => o.description);
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(cards ? 'grid grid-cols-2 gap-2 @lg:grid-cols-4' : 'bg-muted inline-flex max-w-full flex-wrap gap-1 rounded-lg p-1', className)}
    >
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={cn(
              'focus-visible:ring-ring/50 text-sm transition-colors outline-none focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50',
              cards
                ? cn('flex flex-col gap-1 rounded-lg border p-3 text-left', selected ? 'border-primary bg-primary/10' : 'hover:bg-muted/50')
                : cn('rounded-md px-3 py-1.5 font-medium', selected ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'),
            )}
          >
            <span className={cards ? 'font-medium' : undefined}>{o.label}</span>
            {o.description && <span className="text-muted-foreground text-xs">{o.description}</span>}
          </button>
        );
      })}
    </div>
  );
}
