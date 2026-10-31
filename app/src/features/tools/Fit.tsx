import { useState } from 'react';
import { Timer } from 'lucide-react';
import { api, apiUrl } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, Field, message, Muted } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export function Fit() {
  const [file, setFile] = useState<File | null>(null);
  const [seconds, setSeconds] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ url: string; original_seconds: number } | null>(null);
  const [error, setError] = useState('');

  async function run() {
    if (!file) return;
    setBusy(true);
    setError('');
    setResult(null);
    const form = new FormData();
    form.append('file', file);
    form.append('target_seconds', seconds);
    try {
      setResult(await api('/api/tools/fit', { method: 'POST', body: form }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Field label="Audio" hint="WAV, MP3, FLAC or OGG">
        <FileDrop file={file} onFile={setFile} accept=".wav,.mp3,.flac,.ogg,audio/*" disabled={busy} />
      </Field>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="New length in seconds" htmlFor="fit-seconds" className="w-48">
          <Input id="fit-seconds" type="number" min={0.1} step={0.1} value={seconds} onChange={(e) => setSeconds(e.target.value)} placeholder="e.g. 12.5" />
        </Field>
        <Button disabled={busy || !file || !(Number(seconds) > 0)} onClick={run}>
          <Timer /> {busy ? 'Fitting…' : 'Fit'}
        </Button>
      </div>
      <ErrorAlert message={error} />
      {result && (
        <>
          <Muted>Was {result.original_seconds.toFixed(2)} s, now {Number(seconds).toFixed(2)} s.</Muted>
          <AudioResult src={apiUrl(result.url)} download="fitted.wav" />
        </>
      )}
    </>
  );
}
