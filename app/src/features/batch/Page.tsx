import { useEffect, useRef, useState } from 'react';
import { api, listVoices, sendJson, type Voice } from '../../api';
import { LANGUAGES } from '../dubbing/languages';

interface QueuedJob {
  name: string;
  id: string;
}

interface JobStatus {
  state: 'queued' | 'running' | 'done' | 'error';
  step: string;
  percent: number;
  error: string | null;
}

interface WatchedFile {
  name: string;
  status: 'new' | 'dubbing' | 'saved' | 'failed';
  error: string | null;
  step?: string;
  percent?: number;
}

interface WatchState {
  enabled: boolean;
  folder: string;
  target_language: string;
  voice: string;
  problem: string | null;
  output_folder: string;
  skipped: number;
  files: WatchedFile[];
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Page() {
  const [voices, setVoices] = useState<Voice[]>([]);
  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
  }, []);

  return (
    <section className="page">
      <h1>Batch dub</h1>
      <Queue voices={voices} />
      <WatchFolder voices={voices} />
    </section>
  );
}

function Settings({ voices, language, setLanguage, voice, setVoice }: {
  voices: Voice[];
  language: string;
  setLanguage: (v: string) => void;
  voice: string;
  setVoice: (v: string) => void;
}) {
  return (
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
  );
}

function Queue({ voices }: { voices: Voice[] }) {
  const [files, setFiles] = useState<File[]>([]);
  const [language, setLanguage] = useState('es');
  const [voice, setVoice] = useState('original');
  const [queued, setQueued] = useState<QueuedJob[]>([]);
  const [rejected, setRejected] = useState<{ name: string; error: string }[]>([]);
  const [statuses, setStatuses] = useState<Record<string, JobStatus>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const poll = async (jobs: QueuedJob[]) => {
    const entries = await Promise.all(
      jobs.map((j) => api<JobStatus>(`/api/dubbing/jobs/${j.id}`).then((s) => [j.id, s] as const, () => null)),
    );
    const next = Object.fromEntries(entries.filter((e) => e !== null));
    setStatuses(next);
    if (Object.values(next).some((s) => s.state === 'queued' || s.state === 'running')) {
      timer.current = window.setTimeout(() => poll(jobs), 1500);
    }
  };

  async function start() {
    setBusy(true);
    setError('');
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    form.append('target_language', language);
    form.append('voice', voice);
    try {
      const res = await api<{ jobs: QueuedJob[]; errors: { name: string; error: string }[] }>('/api/batch/jobs', { method: 'POST', body: form });
      setQueued(res.jobs);
      setRejected(res.errors);
      setFiles([]);
      window.clearTimeout(timer.current);
      await poll(res.jobs);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2>Dub several videos</h2>
      <label className="field">
        Videos
        <input key={busy ? 'b' : 'i'} type="file" multiple accept="video/*,.mkv" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
      </label>
      <Settings voices={voices} language={language} setLanguage={setLanguage} voice={voice} setVoice={setVoice} />
      <div className="row">
        <button className="primary" disabled={busy || files.length === 0} onClick={start}>
          {busy ? 'Uploading…' : files.length > 1 ? `Dub ${files.length} videos` : 'Dub'}
        </button>
      </div>
      <small className="meta">Dubs run one at a time. You can leave this page; finished dubs appear in Projects.</small>
      {error && <p className="error">{error}</p>}
      {rejected.map((r) => (
        <p key={r.name} className="error">
          {r.name}: {r.error}
        </p>
      ))}
      {queued.map((j) => {
        const s = statuses[j.id];
        return (
          <div key={j.id} className="row">
            <span style={{ flex: 1 }}>{j.name}</span>
            {!s ? <span className="meta">…</span>
              : s.state === 'done' ? <span>Done</span>
              : s.state === 'error' ? <span className="error">{s.error}</span>
              : <span className="meta">{s.step} {s.state === 'running' && `${s.percent}%`}</span>}
          </div>
        );
      })}
    </div>
  );
}

const STATUS_LABELS: Record<WatchedFile['status'], string> = {
  new: 'Waiting for the file to finish copying',
  dubbing: 'Dubbing',
  saved: 'Saved',
  failed: 'Failed',
};

function WatchFolder({ voices }: { voices: Voice[] }) {
  const [state, setState] = useState<WatchState | null>(null);
  const [folder, setFolder] = useState('');
  const [language, setLanguage] = useState('es');
  const [voice, setVoice] = useState('original');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const timer = useRef<number | undefined>(undefined);

  const refresh = async (fillForm = false) => {
    window.clearTimeout(timer.current);
    try {
      const s = await api<WatchState>('/api/batch/watch');
      setState(s);
      if (fillForm && s.folder) {
        setFolder(s.folder);
        setLanguage(s.target_language || 'es');
        setVoice(s.voice);
      }
      if (s.enabled) timer.current = window.setTimeout(() => refresh(), 3000);
    } catch (e) {
      setError(message(e));
    }
  };
  useEffect(() => {
    void refresh(true);
    return () => window.clearTimeout(timer.current);
  }, []);

  async function save(enabled: boolean) {
    setBusy(true);
    setError('');
    try {
      setState(await sendJson<WatchState>('/api/batch/watch', 'PUT', { enabled, folder, target_language: language, voice }));
      void refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2>Watch a folder</h2>
      <p className="meta">
        New videos added to the folder are dubbed automatically and saved in a “{state?.output_folder ?? 'dubbed'}” folder inside it.
        Videos already there when you start are skipped.
      </p>
      <label className="field">
        Folder
        <input value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="C:\Users\you\Videos\To dub" disabled={state?.enabled} />
      </label>
      <Settings voices={voices} language={language} setLanguage={setLanguage} voice={voice} setVoice={setVoice} />
      <div className="row">
        {state?.enabled ? (
          <button className="secondary" disabled={busy} onClick={() => save(false)}>Stop watching</button>
        ) : (
          <button className="primary" disabled={busy || !folder.trim()} onClick={() => save(true)}>Start watching</button>
        )}
        {state?.enabled && <span className="meta">Watching · {state.skipped} existing video(s) skipped</span>}
      </div>
      {error && <p className="error">{error}</p>}
      {state?.problem && <p className="error">{state.problem}</p>}
      {state?.files.map((f) => (
        <div key={f.name} className="row">
          <span style={{ flex: 1 }}>{f.name}</span>
          <span className={f.status === 'failed' ? 'error' : 'meta'}>
            {f.status === 'failed' ? f.error : f.status === 'dubbing' && f.step ? `${f.step} ${f.percent ?? 0}%` : STATUS_LABELS[f.status]}
          </span>
        </div>
      ))}
    </div>
  );
}
