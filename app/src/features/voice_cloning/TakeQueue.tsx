import { AlertCircle, Check, Clock, Loader2, X } from 'lucide-react';
import { Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { clearFinished, removeTake, removeWaiting, takeLabel, type Take } from './queue';

const ICONS = {
  waiting: { icon: Clock, className: 'text-muted-foreground' },
  running: { icon: Loader2, className: 'text-primary animate-spin' },
  done: { icon: Check, className: 'text-success' },
  failed: { icon: AlertCircle, className: 'text-destructive' },
};

const WORDS = { waiting: 'Waiting', running: 'Generating', done: 'Done', failed: 'Failed' };

/** Takes added while another renders: waiting, running and recently finished. */
export function TakeQueue({ takes }: { takes: Take[] }) {
  const waiting = takes.filter((t) => t.status === 'waiting').length;
  const finished = takes.some((t) => t.status === 'done' || t.status === 'failed');
  // One take on its own needs no list, unless it failed and the list is where its error shows.
  if (takes.length <= 1 && !waiting && !takes.some((t) => t.status === 'failed')) return null;

  let place = 0;
  return (
    <Section
      title="Take queue"
      action={
        <div className="flex flex-wrap justify-end gap-1">
          {finished && <Button variant="ghost" size="sm" onClick={clearFinished}>Clear finished</Button>}
          {waiting > 0 && <Button variant="ghost" size="sm" onClick={removeWaiting}>Remove waiting</Button>}
        </div>
      }
    >
      <p className="sr-only" aria-live="polite">{waiting} waiting</p>
      <ol className="max-h-56 divide-y overflow-y-auto">
        {takes.map((t) => {
          const { icon: Icon, className } = ICONS[t.status];
          const label = takeLabel(t.text);
          const state = t.status === 'waiting' ? `#${++place} in line` : WORDS[t.status];
          return (
            <li key={t.id} className="flex items-start gap-3 py-2">
              <Icon className={cn('mt-0.5 size-4 shrink-0', className)} aria-hidden />
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-sm font-medium">{label}</span>
                <span className="text-muted-foreground text-xs">{t.voiceName} · {state}</span>
                {t.error && <span role="alert" className="text-destructive line-clamp-2 text-xs break-words">{t.error}</span>}
              </div>
              {t.status === 'waiting' && (
                <Button variant="ghost" size="icon" className="size-8 shrink-0" aria-label={`Remove from queue: ${label}`} onClick={() => removeTake(t.id)}>
                  <X />
                </Button>
              )}
            </li>
          );
        })}
      </ol>
    </Section>
  );
}
