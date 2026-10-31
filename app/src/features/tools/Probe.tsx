import { useState } from 'react';
import { api } from '../../api';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, message } from '@/components/page';

interface ProbeInfo {
  format: string | null;
  duration: number | null;
  size: number | null;
  bit_rate: number | null;
  streams: { type: string; codec: string; sample_rate?: number; channels?: number; width?: number; height?: number; fps?: number; language?: string }[];
}

const megabytes = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`;

export function Probe() {
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<ProbeInfo | null>(null);
  const [error, setError] = useState('');

  async function run(file: File) {
    setBusy(true);
    setError('');
    setInfo(null);
    const form = new FormData();
    form.append('file', file);
    try {
      setInfo(await api<ProbeInfo>('/api/tools/probe', { method: 'POST', body: form }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <FileDrop
        file={null}
        onFile={(f) => f && run(f)}
        accept="audio/*,video/*,.mkv"
        disabled={busy}
        label={busy ? 'Reading…' : 'Drop an audio or video file here or click to choose'}
      />
      <ErrorAlert message={error} />
      {info && (
        <div className="flex flex-col gap-1 rounded-lg border p-4 text-sm">
          <span className="font-medium">{info.format}</span>
          <span>
            {info.duration !== null && `${info.duration.toFixed(2)} s`}
            {info.size !== null && ` · ${megabytes(info.size)}`}
            {info.bit_rate !== null && ` · ${Math.round(info.bit_rate / 1000)} kb/s`}
          </span>
          {info.streams.map((s, i) => (
            <span key={i} className="text-muted-foreground">
              {s.type === 'video' ? 'Video' : s.type === 'audio' ? 'Audio' : 'Subtitles'}: {s.codec}
              {s.width && ` · ${s.width}×${s.height}`}
              {s.fps && ` · ${s.fps} fps`}
              {s.sample_rate && ` · ${s.sample_rate} Hz`}
              {s.channels && ` · ${s.channels === 1 ? 'mono' : s.channels === 2 ? 'stereo' : `${s.channels} channels`}`}
              {s.language && ` · ${s.language}`}
            </span>
          ))}
        </div>
      )}
    </>
  );
}
