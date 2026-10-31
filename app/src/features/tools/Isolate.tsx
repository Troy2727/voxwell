import { useState } from 'react';
import { AudioLines } from 'lucide-react';
import { api, apiUrl } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, Field, message, Muted } from '@/components/page';
import { Button } from '@/components/ui/button';

type Isolated = { voice: { url: string }; background: { url: string }; seconds: number };

export function Isolate() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Isolated | null>(null);
  const [error, setError] = useState('');

  async function run() {
    if (!file) return;
    setBusy(true);
    setError('');
    setResult(null);
    const form = new FormData();
    form.append('file', file);
    try {
      setResult(await api<Isolated>('/api/tools/isolate', { method: 'POST', body: form }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Field label="Recording" hint="WAV, MP3, FLAC or OGG, up to 10 minutes">
        <FileDrop file={file} onFile={setFile} accept=".wav,.mp3,.flac,.ogg,audio/*" disabled={busy} />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy || !file} onClick={run}>
          <AudioLines /> {busy ? 'Isolating…' : 'Isolate voice'}
        </Button>
        {busy && <Muted>The first time downloads the isolation model (84 MB). A minute of audio takes about 20 seconds on a CPU.</Muted>}
      </div>
      <ErrorAlert message={error} />
      {result && (
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Voice">
            <AudioResult src={apiUrl(result.voice.url)} download="voice.wav" />
          </Field>
          <Field label="Background">
            <AudioResult src={apiUrl(result.background.url)} download="background.wav" />
          </Field>
        </div>
      )}
    </>
  );
}
