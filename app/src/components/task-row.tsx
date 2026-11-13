import { useState, type ReactNode } from 'react';
import { ChevronRight, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/* Adapted from Beautiful UI's TaskRows (https://github.com/slev12397/beautiful-ui),
 * MIT License, Copyright (c) 2026 Shane Levine. */

export type TaskState = 'queued' | 'running' | 'done' | 'failed';

const LABELS: Record<TaskState, string> = { queued: 'Queued', running: 'Running', done: 'Done', failed: 'Failed' };

const PILL: Record<TaskState, string> = {
  queued: 'bg-muted text-muted-foreground',
  running: 'bg-primary/12 text-primary',
  done: 'bg-success/15 text-success',
  failed: 'bg-destructive/12 text-destructive',
};

const RING: Record<TaskState, string> = {
  queued: 'text-border',
  running: 'text-primary',
  done: 'text-success',
  failed: 'text-destructive',
};

/** How far along a task is, as a ring that fills clockwise. */
function ProgressRing({ state, percent }: { state: TaskState; percent: number }) {
  const r = 7.5;
  const c = 2 * Math.PI * r;
  const filled = state === 'done' || state === 'failed' ? 1 : percent / 100;
  return (
    <svg viewBox="0 0 18 18" className={cn('size-[18px] shrink-0', RING[state])} aria-hidden>
      <circle cx="9" cy="9" r={r} fill="none" strokeWidth="2.4" className="stroke-border" />
      <circle
        cx="9" cy="9" r={r} fill="none" strokeWidth="2.4" stroke="currentColor" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - filled)} transform="rotate(-90 9 9)"
        className="transition-[stroke-dashoffset] duration-500"
      />
    </svg>
  );
}

/** One task in a list: ring, name, status pill and details that expand. A failed task shows its
 *  error without expanding and offers Retry when `onRetry` is given. */
export function TaskRow({ name, state, percent = 0, detail, onRetry }: {
  name: string;
  state: TaskState;
  percent?: number;
  detail?: ReactNode;
  onRetry?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const shown = open || state === 'failed';
  return (
    <div className="py-2" data-task-state={state}>
      <div className="flex items-center gap-3 text-sm">
        <ProgressRing state={state} percent={percent} />
        <span className="min-w-0 flex-1 truncate">{name}</span>
        {state === 'failed' && onRetry && (
          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={onRetry}>
            <RotateCcw /> Retry
          </Button>
        )}
        <span className={cn('shrink-0 rounded-full px-2 py-0.5 text-xs font-medium', PILL[state])}>
          {LABELS[state]}
          {state === 'running' && percent > 0 && <span className="tabular-nums"> {Math.round(percent)}%</span>}
        </span>
        {detail && state !== 'failed' && (
          <Button variant="ghost" size="icon" className="size-7 shrink-0" aria-label={`Details for ${name}`} aria-expanded={open} onClick={() => setOpen(!open)}>
            <ChevronRight className={cn('transition-transform', open && 'rotate-90')} />
          </Button>
        )}
      </div>
      {detail && shown && (
        <p className={cn('mt-1.5 pl-[30px] text-xs break-words', state === 'failed' ? 'text-destructive' : 'text-muted-foreground')}>{detail}</p>
      )}
    </div>
  );
}
