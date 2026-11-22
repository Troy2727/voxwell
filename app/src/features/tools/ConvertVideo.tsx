import { useState } from 'react';
import { Download, Video } from 'lucide-react';
import { api, apiUrl, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { FileDrop } from '@/components/file-drop';
import { JobProgress } from '@/components/job-progress';
import { ErrorAlert, Field, message, Muted } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';

interface Result {
  url: string;
  video_url: string | null;
  notes: string[];
}

/** Convert video: the voice in a video swapped for a saved voice; picture and background stay. */
export function ConvertVideo({ voices }: { voices: Voice[] }) {
  const [file, setFile] = useState<File | null>(null);
  const [voice, setVoice] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');

  const choose = (next: File | null) => {
    setFile(next);
    setResult(null);
    setError('');
  };

  async function run() {
    if (!file) return;
    setBusy(true);
    setError('');
    setResult(null);
    const form = new FormData();
    form.append('file', file);
    form.append('voice_id', voice);
    try {
      setResult(await api<Result>('/api/tools/convert-video', { method: 'POST', body: form }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Field label="Video" hint="MP4, MOV, MKV or WebM, up to 10 minutes">
        <FileDrop file={file} onFile={choose} accept="video/*,.mkv" disabled={busy} />
      </Field>
      <Field label="New voice" hint={voices.length === 0 ? 'Add a voice in Voice cloning, Voice design or Gallery first.' : undefined}>
        <VoiceSelect voices={voices} value={voice} onChange={setVoice} defaultLabel={null} />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button className="max-w-full" disabled={busy || !file || !voice} onClick={run}>
          <Video /> {busy ? 'Converting…' : 'Convert video'}
        </Button>
      </div>
      {busy && <JobProgress step="Converting the voice" percent={null} hint="This can take several minutes. The first time downloads the conversion and voice isolation models." />}
      <ErrorAlert message={error} />
      {result?.video_url && (
        <div className="flex flex-col gap-3">
          <video controls src={apiUrl(result.video_url)} className="max-h-60 max-w-full rounded-lg border" />
          <div>
            <Button asChild variant="outline" className="max-w-full">
              <a href={apiUrl(result.video_url)} download="converted.mp4">
                <Download /> Download video
              </a>
            </Button>
          </div>
        </div>
      )}
      {result && !result.video_url && <AudioResult src={apiUrl(result.url)} download="converted.wav" />}
      {result?.notes.map((note) => (
        <Muted key={note}>{note}</Muted>
      ))}
    </>
  );
}
