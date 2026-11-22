import { Switch } from '@/components/ui/switch';

/** Natural pauses: pauses carry the recording's own quiet background instead of silence. Off by default. */
export function NaturalPauses({ checked, onChange, disabled }: { checked: boolean; onChange: (on: boolean) => void; disabled?: boolean }) {
  return (
    <label className="flex items-start gap-3 text-sm">
      <Switch className="mt-0.5" checked={checked} disabled={disabled} onCheckedChange={onChange} aria-label="Natural pauses" />
      <span>
        <span className="font-medium">Natural pauses</span>
        <span className="text-muted-foreground block">Fill pauses with the quiet background of the recording instead of silence.</span>
      </span>
    </label>
  );
}
