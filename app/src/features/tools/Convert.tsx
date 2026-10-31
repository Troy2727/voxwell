import { useState } from 'react';
import { ArrowRightLeft } from 'lucide-react';
import { api, apiUrl, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, Field, message, Muted } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';

export function Convert({ voices }: { voices: Voice[] }) {
  const [file, setFile] = useState<File | null>(null);
  const [voice, setVoice] = useState('');
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');

  async function run() {
    if (!file) return;
    setBusy(true);
    setError('');
    setUrl('');
    const form = new FormData();
    form.append('file', file);
    form.append('voice_id', voice);
    try {
      setUrl((await api<{ url: string }>('/api/tools/convert', { method: 'POST', body: form })).url);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Field label="Recording" hint="WAV, MP3, FLAC or OGG">
        <FileDrop file={file} onFile={setFile} accept=".wav,.mp3,.flac,.ogg,audio/*" disabled={busy} />
      </Field>
      <Field label="New voice" hint={voices.length === 0 ? 'Add a voice in Voice cloning, Voice design or Gallery first.' : undefined}>
        <VoiceSelect voices={voices} value={voice} onChange={setVoice} defaultLabel={null} />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy || !file || !voice} onClick={run}>
          <ArrowRightLeft /> {busy ? 'Converting…' : 'Convert'}
        </Button>
        {busy && <Muted>The first time downloads the conversion model.</Muted>}
      </div>
      <ErrorAlert message={error} />
      {url && <AudioResult src={apiUrl(url)} download="converted.wav" />}
    </>
  );
}
