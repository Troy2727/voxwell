import { useRef, type ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

const SECTIONS = ['Verse', 'Pre-Chorus', 'Chorus', 'Bridge', 'Outro'];

/** Song lyrics with buttons that insert section tags ([Verse], [Chorus], …) at the cursor.
 *  `actions` sits at the end of the tag row, e.g. a "Write with AI" button. */
export function LyricsEditor({ id, value, onChange, maxLength, disabled, actions }: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  maxLength: number;
  disabled?: boolean;
  actions?: ReactNode;
}) {
  const area = useRef<HTMLTextAreaElement>(null);

  function insert(section: string) {
    const el = area.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    const before = value.slice(0, start);
    const tag = `${before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : ''}[${section}]\n`;
    const next = (before + tag + value.slice(end)).slice(0, maxLength);
    onChange(next);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(before.length + tag.length, before.length + tag.length);
    });
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {SECTIONS.map((s) => (
          <Button key={s} type="button" variant="outline" size="sm" className="h-7 px-2 text-xs" disabled={disabled} onClick={() => insert(s)}>
            [{s}]
          </Button>
        ))}
        {actions && <div className="ml-auto flex flex-wrap gap-2">{actions}</div>}
      </div>
      <Textarea
        ref={area}
        id={id}
        rows={9}
        maxLength={maxLength}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={'[Verse 1]\nWrite your lines here\n\n[Chorus]\nThe part everyone sings along to'}
        className="font-mono text-sm"
      />
      <p className="text-muted-foreground text-right text-xs tabular-nums">{value.length} / {maxLength}</p>
    </div>
  );
}
