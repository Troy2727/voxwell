import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

/** Tells the backend which speaker options to use: "speakers" and "num_speakers" form fields. */
export function appendSpeakerFields(form: FormData, enabled: boolean, count: string) {
  if (!enabled) return;
  form.append('speakers', 'true');
  form.append('num_speakers', count.trim() || '0');
}

/** "Label speakers" with an optional head count (blank: find out). Off unless the user turns it on. */
export function SpeakerOptions({ enabled, onEnabled, count, onCount, disabled, hint }: {
  enabled: boolean;
  onEnabled: (enabled: boolean) => void;
  count: string;
  onCount: (count: string) => void;
  disabled?: boolean;
  hint: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-2">
          <Checkbox id="label-speakers" checked={enabled} disabled={disabled} onCheckedChange={(v) => onEnabled(v === true)} />
          <Label htmlFor="label-speakers">Label speakers</Label>
        </div>
        {enabled && (
          <div className="flex items-center gap-2">
            <Label htmlFor="speaker-count" className="text-muted-foreground font-normal">
              Number of speakers
            </Label>
            <Input
              id="speaker-count"
              type="number"
              min={1}
              max={20}
              placeholder="Auto"
              value={count}
              disabled={disabled}
              onChange={(e) => onCount(e.target.value)}
              className="w-24"
            />
          </div>
        )}
      </div>
      <p className="text-muted-foreground text-xs">{hint}</p>
    </div>
  );
}
