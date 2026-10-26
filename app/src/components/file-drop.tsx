import { useRef, useState } from 'react';
import { FileUp, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

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

  const pick = (list: FileList | null) => {
    const files = Array.from(list ?? []);
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
      onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}
      className={cn(
        'text-muted-foreground hover:border-primary/60 hover:bg-muted/40 flex w-full flex-col items-center gap-1 rounded-lg border border-dashed px-4 py-6 text-sm transition-colors disabled:pointer-events-none disabled:opacity-50',
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
