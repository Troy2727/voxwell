import { X } from 'lucide-react';
import { Section } from '@/components/page';
import { TaskRow, type TaskState } from '@/components/task-row';
import { Button } from '@/components/ui/button';
import { clearFinished, removeTake, removeWaiting, takeLabel, type Take } from './queue';

const STATES: Record<Take['status'], TaskState> = { waiting: 'queued', running: 'running', done: 'done', failed: 'failed' };

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
          const label = takeLabel(t.text);
          const status = t.status === 'waiting' ? `Position ${++place}` : WORDS[t.status];
          return (
            <li key={t.id}>
              <TaskRow
                name={label}
                state={STATES[t.status]}
                status={status}
                detail={t.error ?? `Voice: ${t.voiceName}`}
                action={
                  t.status === 'waiting' && (
                    <Button variant="ghost" size="icon" className="size-7 shrink-0" aria-label={`Drop this take: ${label}`} onClick={() => removeTake(t.id)}>
                      <X />
                    </Button>
                  )
                }
              />
            </li>
          );
        })}
      </ol>
    </Section>
  );
}
