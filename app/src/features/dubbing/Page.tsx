import { useEffect, useRef, useState } from 'react';
import { api, apiUrl, listVoices, type Voice } from '../../api';
import { LANGUAGES } from './languages';

interface JobStatus {
  id: string;
  state: 'queued' | 'running' | 'done' | 'error';
  step: string;
  percent: number;
  error: string | null;
}

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState('es');
  const [voice, setVoice] = useState('original');
  const [voices, setVoices] = useState<Voice[]>([]);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
    return () => window.clearTimeout(timer.current);
  }, []);

  const poll = (id: string) => {
    api<JobStatus>(`/api/dubbing/jobs/${id}`).then(
      (status) => {
        setJob(status);
        if (status.state === 'queued' || status.state === 'running') {
          timer.current = window.setTimeout(() => poll(id), 1000);
        } else {
          setBusy(false);
        }
      },
      (e: Error) => {
        setError(e.message);
        setBusy(false);
      },
    );
  };

  const start = async () => {
    if (!file) return;
    setError(null);
    setJob(null);
    setBusy(true);
    const form = new FormData();
    form.append('file', file);
    form.append('target_language', language);
    form.append('voice', voice);
    try {
      const { id } = await api<{ id: string }>('/api/dubbing/jobs', { method: 'POST', body: form });
      poll(id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const failed = job?.state === 'error';

  return (
    <section className="page">
      <h1>Dubbing</h1>
      <div className="card">
        <label className="field">
          Video
          <input type="file" accept="video/*,.mkv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <div className="row">
          <label className="field">
            Target language
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map(([code, name]) => (
                <option key={code} value={code}>{name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Voice
            <select value={voice} onChange={(e) => setVoice(e.target.value)}>
              <option value="original">Original speaker</option>
              {voices.map((v) => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </select>
          </label>
        </div>
        {voices.length === 0 && <small>No saved voices yet; create one in Voice cloning or Voice design.</small>}
        <div className="row">
          <button className="primary" disabled={!file || busy} onClick={start}>
            {busy ? 'Dubbing…' : 'Start'}
          </button>
        </div>
      </div>

      {job && !failed && job.state !== 'done' && (
        <div className="card">
          <div>{job.step}</div>
          <progress max={100} value={job.percent} style={{ width: '100%' }} />
          <small>You can leave this page; the dub keeps going and appears in Projects.</small>
        </div>
      )}
      {(error || failed) && <p className="error">{error ?? job?.error}</p>}

      {job?.state === 'done' && (
        <div className="card">
          <video controls src={apiUrl(`/api/dubbing/jobs/${job.id}/video`)} />
          <div className="row">
            <a href={apiUrl(`/api/dubbing/jobs/${job.id}/video`)} download="dubbed.mp4">Download video</a>
            <a href={apiUrl(`/api/dubbing/jobs/${job.id}/subtitles`)} download="subtitles.srt">Download subtitles</a>
          </div>
        </div>
      )}
    </section>
  );
}
