import { useState, type ReactNode } from 'react';
import { Scissors } from 'lucide-react';
import { toast } from 'sonner';
import { editSection, formatTime, type Track } from './api';
import { ErrorAlert, Field, message, Muted } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Slider } from '@/components/ui/slider';
import { Textarea } from '@/components/ui/textarea';

const MIN_SECONDS = 3;

/** Pick a stretch of a finished track and regenerate just that part; the result is a new track. */
export function EditSectionDialog({ track, onQueued, children }: { track: Track; onQueued: (track: Track) => void; children: ReactNode }) {
  const length = track.duration;
  const [open, setOpen] = useState(false);
  const [range, setRange] = useState<[number, number]>([Math.min(length / 3, length - MIN_SECONDS), Math.min((length * 2) / 3, length)]);
  const [prompt, setPrompt] = useState('');
  const [lyrics, setLyrics] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit() {
    setBusy(true);
    setError('');
    try {
      onQueued(await editSection(track.id, { start: range[0], end: range[1], prompt, lyrics }));
      toast.success('Regenerating the section as a new track');
      setOpen(false);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit a section</DialogTitle>
          <DialogDescription>
            Regenerate part of “{track.title}”. The rest of the track stays as it is; the result is saved as a new track.
          </DialogDescription>
        </DialogHeader>
        <Field label={`Section: ${formatTime(range[0])} – ${formatTime(range[1])}`} hint={`At least ${MIN_SECONDS} seconds; the track is ${formatTime(length)} long.`}>
          <Slider
            aria-label="Section to regenerate"
            min={0}
            max={length}
            step={0.5}
            minStepsBetweenThumbs={MIN_SECONDS * 2}
            value={range}
            onValueChange={(v) => setRange([v[0], v[1]])}
          />
        </Field>
        <Field label="New style for this part (optional)" htmlFor="edit-prompt">
          <Textarea id="edit-prompt" rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={track.prompt} />
        </Field>
        {!track.instrumental && (
          <Field label="Lyrics (optional)" htmlFor="edit-lyrics" hint="Leave empty to keep the original lyrics.">
            <Textarea id="edit-lyrics" rows={4} value={lyrics} onChange={(e) => setLyrics(e.target.value)} className="font-mono text-sm" />
          </Field>
        )}
        <ErrorAlert message={error} />
        <DialogFooter className="items-center gap-2">
          {busy && <Muted>Queuing…</Muted>}
          <Button onClick={submit} disabled={busy || range[1] - range[0] < MIN_SECONDS}>
            <Scissors /> Regenerate section
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
