import { useEffect, useId, useState, type ReactNode } from 'react';
import { Progress } from '@/components/ui/progress';

/* The pixel-grid loader and elapsed timer are adapted from Beautiful UI's LoadingState
 * (https://github.com/slev12397/beautiful-ui), MIT License, Copyright (c) 2026 Shane Levine. */

// A chevron wavefront driving right across a 3x3 grid: each cell's delay in ms.
const DELAYS = Array.from({ length: 9 }, (_, i) => ((i % 3) + Math.abs(Math.floor(i / 3) - 1)) * 90);

function PixelGrid() {
  return (
    <span aria-hidden data-pixel-grid className="grid shrink-0 grid-cols-[repeat(3,4px)] gap-[1.5px]">
      {DELAYS.map((delay, i) => (
        <span key={i} className="pixel-on bg-primary size-[4px] rounded-[1px] opacity-15" style={{ animationDelay: `${delay}ms` }} />
      ))}
    </span>
  );
}

/** Time since the component mounted, as "4.2s" or "1m 3.0s". */
function useElapsed() {
  const [tenths, setTenths] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTenths((d) => d + 1), 100);
    return () => clearInterval(t);
  }, []);
  const total = tenths / 10;
  return total < 60 ? `${total.toFixed(1)}s` : `${Math.floor(total / 60)}m ${(total % 60).toFixed(1)}s`;
}

/** A running job: current step, time elapsed, a progress bar and an optional hint underneath. A
 *  `percent` of null means the job does not report how far along it is: the bar pulses instead.
 *  Screen readers hear each new step (not every percent or tick) and can read the bar by its step. */
export function JobProgress({ step, percent, hint }: { step: ReactNode; percent: number | null; hint?: ReactNode }) {
  const stepId = useId();
  const elapsed = useElapsed();
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2.5 text-sm">
        <PixelGrid />
        <span id={stepId} role="status" className="shimmer-text flex-1">{step}</span>
        <span data-elapsed className="text-muted-foreground font-mono text-xs tabular-nums" aria-hidden>{elapsed}</span>
        {percent !== null && <span className="text-muted-foreground tabular-nums" aria-hidden>{Math.round(percent)}%</span>}
      </div>
      {percent === null ? (
        <Progress value={null} aria-labelledby={stepId} className="animate-pulse opacity-40" />
      ) : (
        <Progress value={percent} aria-labelledby={stepId} />
      )}
      {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
    </div>
  );
}
