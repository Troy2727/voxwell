import { useState } from 'react';
import { Check, Pencil, Repeat, Scissors, SplitSquareHorizontal, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { apiUrl } from '../../api';
import { deleteTrack, formatTime, renameTrack, splitStems, type Settings, type Track } from './api';
import { EditSectionDialog } from './EditSection';
import { AudioResult } from '@/components/audio-result';
import { ConfirmButton } from '@/components/confirm-button';
import { JobProgress } from '@/components/job-progress';
import { ErrorAlert, message, Muted } from '@/components/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export function TrackCard({ track, onChanged, onDeleted, onQueued, onReuse }: {
  track: Track;
  onChanged: (track: Track) => void;
  onDeleted: () => void;
  onQueued: (track: Track) => void;
  onReuse: (settings: Settings) => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(track.title);
  const [splitting, setSplitting] = useState(false);
  const [error, setError] = useState('');
  const pending = track.status === 'queued' || track.status === 'generating';
  const fileBase = track.title.replace(/[\\/:*?"<>|]/g, '').slice(0, 60) || 'voxwell-music';

  async function run(action: () => Promise<void>) {
    setError('');
    try {
      await action();
    } catch (e) {
      setError(message(e));
    }
  }

  const saveTitle = () =>
    run(async () => {
      onChanged(await renameTrack(track.id, title));
      setRenaming(false);
    });

  const split = () =>
    run(async () => {
      setSplitting(true);
      try {
        onChanged(await splitStems(track.id));
        toast.success('Split into vocals and instrumental');
      } finally {
        setSplitting(false);
      }
    });

  const remove = () =>
    run(async () => {
      await deleteTrack(track.id);
      onDeleted();
      toast.success('Deleted');
    });

  const reuse = () =>
    onReuse({
      prompt: track.prompt,
      lyrics: track.lyrics,
      instrumental: track.instrumental,
      language: track.language,
      duration: Math.round(track.duration),
      bpm: track.bpm ? String(track.bpm) : '',
      key: track.key,
      seed: String(track.seed),
      steps: track.steps,
    });

  return (
    <article className="flex flex-col gap-3 rounded-lg border p-3" aria-busy={pending}>
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          {renaming ? (
            <div className="flex items-center gap-1">
              <Input value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} aria-label="Track title" className="h-8" autoFocus
                onKeyDown={(e) => { if (e.key === 'Enter' && title.trim()) void saveTitle(); if (e.key === 'Escape') setRenaming(false); }} />
              <Button size="icon" variant="ghost" className="size-8" aria-label="Save title" disabled={!title.trim()} onClick={saveTitle}><Check /></Button>
              <Button size="icon" variant="ghost" className="size-8" aria-label="Cancel" onClick={() => { setTitle(track.title); setRenaming(false); }}><X /></Button>
            </div>
          ) : (
            <p className="font-medium break-words">{track.title}</p>
          )}
          <Muted className="text-xs">
            {[
              formatTime(track.duration),
              track.instrumental ? 'Instrumental' : 'Vocals',
              track.bpm ? `${track.bpm} BPM` : null,
              track.key || null,
              `seed ${track.seed}`,
              new Date(track.created * 1000).toLocaleString(),
            ].filter(Boolean).join(' · ')}
          </Muted>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {track.parent_id && <Badge variant="secondary">Edited {formatTime(track.edit_start ?? 0)}–{formatTime(track.edit_end ?? 0)}</Badge>}
          {track.has_reference && <Badge variant="secondary">Style reference</Badge>}
          {track.status === 'failed' && <Badge variant="destructive">Failed</Badge>}
        </div>
      </div>

      {pending && (
        <JobProgress
          step={track.status === 'queued' ? 'Waiting to start' : track.stage}
          percent={track.progress > 0 ? track.progress * 100 : null}
          hint="You can leave this page; the track keeps generating."
        />
      )}
      {track.status === 'failed' && <ErrorAlert message={track.error} />}
      {track.url && <AudioResult src={apiUrl(track.url)} download={`${fileBase}.wav`} lazy />}
      {track.vocals_url && track.instrumental_url && (
        <div className="grid gap-2 @2xl:grid-cols-2">
          <div className="flex flex-col gap-1">
            <Muted className="text-xs">Vocals</Muted>
            <AudioResult src={apiUrl(track.vocals_url)} download={`${fileBase} (vocals).wav`} lazy />
          </div>
          <div className="flex flex-col gap-1">
            <Muted className="text-xs">Instrumental</Muted>
            <AudioResult src={apiUrl(track.instrumental_url)} download={`${fileBase} (instrumental).wav`} lazy />
          </div>
        </div>
      )}

      <details className="text-sm">
        <summary className="text-muted-foreground cursor-pointer select-none">Style and lyrics</summary>
        <p className="mt-2 break-words">{track.prompt}</p>
        {track.lyrics && <pre className="bg-muted/40 mt-2 rounded-md p-2 font-mono text-xs whitespace-pre-wrap">{track.lyrics}</pre>}
      </details>

      <ErrorAlert message={error} />
      <div className="flex flex-wrap gap-2">
        {track.status === 'done' && (
          <>
            <EditSectionDialog track={track} onQueued={onQueued}>
              <Button variant="outline" size="sm"><Scissors /> Edit a section</Button>
            </EditSectionDialog>
            {!track.stems && !track.instrumental && (
              <Button variant="outline" size="sm" disabled={splitting} onClick={split}>
                <SplitSquareHorizontal /> {splitting ? 'Splitting…' : 'Split vocals'}
              </Button>
            )}
          </>
        )}
        <Button variant="outline" size="sm" onClick={reuse}><Repeat /> Reuse settings</Button>
        {!renaming && (
          <Button variant="outline" size="sm" onClick={() => setRenaming(true)}><Pencil /> Rename</Button>
        )}
        <ConfirmButton title="Delete this track?" onConfirm={remove}>
          <Trash2 /> Delete
        </ConfirmButton>
      </div>
    </article>
  );
}
