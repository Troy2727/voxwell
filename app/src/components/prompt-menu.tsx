import { useId, useState, type KeyboardEvent, type RefObject } from 'react';
import { cn } from '@/lib/utils';

/* The @ / mention menu is adapted from Beautiful UI's PromptBar (https://github.com/slev12397/beautiful-ui),
 * MIT License, Copyright (c) 2026 Shane Levine. */

export interface PromptItem {
  /** What the person types after the trigger to find it, e.g. "Mara" or "pause-long". */
  label: string;
  hint?: string;
  /** Runs on the text with the typed trigger word removed; return new text and cursor to change it. */
  pick: (text: string, at: number) => { text: string; cursor: number } | void;
}

/** One menu per trigger character: '@' for voices, '/' for actions. */
export type PromptSources = Partial<Record<'@' | '/', { title: string; items: PromptItem[] }>>;

/** A trigger word right before the cursor, after a space or at the start: "@ma", "/pa". */
function triggerAt(text: string, cursor: number) {
  const m = text.slice(0, cursor).match(/(^|\s)([@/])([\w-]*)$/);
  return m ? { char: m[2] as '@' | '/', query: m[3], start: cursor - m[3].length - 1 } : null;
}

/**
 * Adds an @ / mention menu to a textarea. Spread `inputProps` on the textarea and render `menu`
 * inside a `relative` wrapper around it. Picking an item removes the typed trigger word, then runs
 * the item's `pick`.
 */
export function usePromptMenu({ box, text, setText, sources, onSubmit }: {
  box: RefObject<HTMLTextAreaElement | null>;
  text: string;
  setText: (text: string) => void;
  sources: PromptSources;
  /** Ctrl+Enter / Cmd+Enter. */
  onSubmit?: () => void;
}) {
  const listId = useId();
  const [trigger, setTrigger] = useState<ReturnType<typeof triggerAt>>(null);
  const [active, setActive] = useState(0);

  const source = trigger ? sources[trigger.char] : undefined;
  const items = source && trigger
    ? source.items.filter((i) => i.label.toLowerCase().startsWith(trigger.query.toLowerCase()))
    : [];
  const open = items.length > 0;

  const update = (value: string, cursor: number) => {
    setTrigger(triggerAt(value, cursor));
    setActive(0);
  };

  const choose = (item: PromptItem) => {
    if (!trigger) return;
    const cursor = box.current?.selectionStart ?? text.length;
    const cleared = text.slice(0, trigger.start) + text.slice(cursor);
    const changed = item.pick(cleared, trigger.start);
    const at = changed ? changed.cursor : trigger.start;
    setText(changed ? changed.text : cleared);
    setTrigger(null);
    requestAnimationFrame(() => {
      box.current?.focus();
      box.current?.setSelectionRange(at, at);
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (open) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        setActive((a) => (a + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length);
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        choose(items[active]);
        return;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setTrigger(null);
        return;
      }
    }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && onSubmit) {
      e.preventDefault();
      onSubmit();
    }
  };

  // A textarea keeps its native textbox role (ARIA allows no other), so no role or aria-expanded.
  const inputProps = {
    'aria-autocomplete': 'list' as const,
    'aria-controls': open ? listId : undefined,
    'aria-activedescendant': open ? `${listId}-${active}` : undefined,
    onKeyDown,
    onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setText(e.target.value);
      update(e.target.value, e.target.selectionStart);
    },
    onClick: (e: React.MouseEvent<HTMLTextAreaElement>) => update(e.currentTarget.value, e.currentTarget.selectionStart),
    onBlur: () => setTrigger(null),
  };

  const menu = open ? (
    <div className="bg-popover text-popover-foreground absolute top-full left-0 z-20 mt-1 w-full max-w-xs rounded-md border p-1 shadow-md">
      <p className="text-muted-foreground px-2 pt-1 pb-1.5 text-xs font-medium">{source!.title}</p>
      <ul id={listId} role="listbox" aria-label={source!.title} className="max-h-64 overflow-y-auto">
        {items.map((item, i) => (
          <li
            key={`${item.label}-${i}`}
            id={`${listId}-${i}`}
            // Arrow keys can move past the visible rows: keep the active one in view.
            ref={i === active ? (el) => el?.scrollIntoView({ block: 'nearest' }) : undefined}
            role="option"
            aria-selected={i === active}
            className={cn('flex cursor-pointer items-baseline justify-between gap-3 rounded-sm px-2 py-1.5 text-sm', i === active && 'bg-accent text-accent-foreground')}
            // mousedown, not click: the textarea would blur first and close the menu.
            onMouseDown={(e) => {
              e.preventDefault();
              choose(item);
            }}
            onMouseEnter={() => setActive(i)}
          >
            <span className="truncate">{item.label}</span>
            {item.hint && <span className="text-muted-foreground shrink-0 text-xs">{item.hint}</span>}
          </li>
        ))}
      </ul>
    </div>
  ) : null;

  return { inputProps, menu };
}
