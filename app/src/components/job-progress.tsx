import { useId, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { Progress } from '@/components/ui/progress';

/** A running job: current step, a progress bar and an optional hint underneath. A `percent` of
 *  null means the job does not report how far along it is: the bar pulses instead.
 *  Screen readers hear each new step (not every percent) and can read the bar by its step. */
export function JobProgress({ step, percent, hint }: { step: ReactNode; percent: number | null; hint?: ReactNode }) {
  const stepId = useId();
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-sm">
        <Loader2 className="text-primary size-4 animate-spin" aria-hidden />
        <span id={stepId} role="status" className="flex-1">{step}</span>
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
