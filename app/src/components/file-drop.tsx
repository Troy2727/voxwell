import { useRef, useState } from 'react';
import { FileUp, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/** Whether a file matches an `<input accept>` list (".wav,audio/*"), as the file picker checks it.
 *  A file the OS gave no type passes a type rule (audio/*): the backend still checks it. */
export function accepts(accept: string | undefined, file: File) {
  if (!accept) return true;
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  return accept.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean).some((t) =>
    t.startsWith('.') ? name.endsWith(t) : !type || (t.endsWith('/*') ? type.startsWith(t.slice(0, -1)) : type === t));
}

/** Click or drop to pick a file (`onFile`) or several (`multiple` + `onFiles`). A picked single
 *  `file` is shown with a remove button; it is controlled so a parent can clear it after use. */
export function FileDrop({ file, onFile, onFiles, multiple, accept, hint, disabled, label = 'Drop a file here or click to choose' }: {
  file: File | null;
  onFile?: (file: File | null) => void;
  onFiles?: (files: File[]) => void;
  multiple?: boolean;
  accept?: string;
  hint?: string;
  disabled?: boolean;
  label?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const pick = (list: FileList | null, dropped = false) => {
    const all = Array.from(list ?? []);
    // The picker already filters by `accept` (a file chosen past it goes on, for the page to judge);
    // a drop skips that filter, so check dropped files the same way.
    const files = dropped ? all.filter((f) => accepts(accept, f)) : all;
    const refused = all.filter((f) => !files.includes(f));
    if (refused.length) toast.error(`This page can't use ${refused.map((f) => f.name).join(', ')}. ${hint ?? 'Choose another file.'}`);
    if (disabled || files.length === 0) return;
    if (onFiles) onFiles(files);
    else onFile?.(files[0]);
  };

  if (file) {
    return (
      <div className="bg-muted/40 flex items-center gap-3 rounded-lg border px-3 py-2 text-sm">
        <FileUp className="text-muted-foreground size-4 shrink-0" />
        <span className="flex-1 truncate">{file.name}</span>
        <span className="text-muted-foreground shrink-0 text-xs">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
        <Button variant="ghost" size="icon" className="size-7" aria-label="Remove file" disabled={disabled} onClick={() => onFile?.(null)}>
          <X />
        </Button>
      </div>
    );
  }

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => input.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files, true); }}
      className={cn(
        // Children ignore the pointer, so dragging across the icon or text does not flicker the highlight.
        'text-muted-foreground hover:border-primary/60 hover:bg-muted/40 focus-visible:border-ring focus-visible:ring-ring/50 flex w-full flex-col items-center gap-1 rounded-lg border border-dashed px-4 py-6 text-sm transition-colors outline-none focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50 [&>*]:pointer-events-none',
        over && 'border-primary bg-muted/40',
      )}
    >
      <FileUp className="size-5" />
      <span className="text-foreground font-medium">{label}</span>
      {hint && <span className="text-xs">{hint}</span>}
      <input ref={input} type="file" accept={accept} multiple={multiple} hidden onChange={(e) => { pick(e.target.files); e.target.value = ''; }} />
    </button>
  );
}
