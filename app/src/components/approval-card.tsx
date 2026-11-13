import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/* Adapted from Beautiful UI's ApprovalCard (https://github.com/slev12397/beautiful-ui),
 * MIT License, Copyright (c) 2026 Shane Levine. */

export interface ApprovalQuestion {
  question: string;
  options: string[];
}

/**
 * Questions asked one at a time before something happens. Picking an answer moves to the next
 * question; after the last one, `onDone` gets every answer in order. `onCancel` drops the action.
 */
export function ApprovalCard({ title, questions, onDone, onCancel }: {
  title: string;
  questions: ApprovalQuestion[];
  onDone: (answers: string[]) => void;
  onCancel: () => void;
}) {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<string[]>([]);
  const first = useRef<HTMLButtonElement>(null);
  const q = questions[step];

  // Each new question takes the keyboard focus, so it can be answered without the mouse.
  useEffect(() => first.current?.focus(), [step]);

  const pick = (option: string) => {
    const next = [...answers.slice(0, step), option];
    setAnswers(next);
    if (step + 1 < questions.length) setStep(step + 1);
    else onDone(next);
  };

  return (
    <div role="group" aria-label={title} className="bg-card overflow-hidden rounded-xl border">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-2.5 text-sm">
        <span className="font-medium">{title}</span>
        {questions.length > 1 && <span className="text-muted-foreground font-mono text-xs tabular-nums">{step + 1}/{questions.length}</span>}
      </div>
      <fieldset key={step} className="animate-in fade-in slide-in-from-bottom-2 motion-reduce:animate-none px-4 py-4 duration-300">
        <legend className="float-left mb-3 w-full text-sm font-semibold">{q.question}</legend>
        <div className="clear-left grid gap-2">
          {q.options.map((option, i) => (
            <button
              key={option}
              ref={i === 0 ? first : undefined}
              type="button"
              aria-pressed={answers[step] === option}
              onClick={() => pick(option)}
              className={cn(
                'hover:border-muted-foreground focus-visible:ring-ring/50 flex items-center gap-3 rounded-lg border px-3 py-2.5 text-left text-sm outline-none focus-visible:ring-[3px]',
                answers[step] === option && 'border-primary bg-primary/5',
              )}
            >
              <span aria-hidden className={cn('size-4 shrink-0 rounded-full border-[1.5px]', answers[step] === option ? 'border-primary bg-primary' : 'border-muted-foreground')} />
              {option}
            </button>
          ))}
        </div>
      </fieldset>
      <div className="flex justify-end gap-2 border-t px-4 py-2.5">
        {step > 0 && <Button variant="ghost" size="sm" onClick={() => setStep(step - 1)}>Back</Button>}
        <Button variant="outline" size="sm" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}
