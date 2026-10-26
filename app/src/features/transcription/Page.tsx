import { useEffect, useRef, useState } from 'react';
import { api, apiUrl } from '../../api';

interface Summary {
  id: string;
  title: string;
  created: number;
  language: string;
  detected: string;
  state: 'queued' | 'running' | 'done' | 'error';
  percent: number;
  error: string | null;
}

interface Segment {
  start: number;
  end: number;
  text: string;
}

interface Detail extends Summary {
  transcript?: { text: string; language: string; segments: Segment[] };
}

const LANGUAGES: [string, string][] = [
  ['', 'Auto-detect'], ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'],
  ['it', 'Italian'], ['pt', 'Portuguese'], ['nl', 'Dutch'], ['ru', 'Russian'], ['zh', 'Chinese'],
  ['ja', 'Japanese'], ['ko', 'Korean'], ['ar', 'Arabic'], ['hi', 'Hindi'], ['tr', 'Turkish'],
];

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const working = (j: Summary) => j.state === 'queued' || j.state === 'running';
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState('');
  const [starting, setStarting] = useState(false);
  const [list, setList] = useState<Summary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState('');
  const timer = useRef<number | undefined>(undefined);

  const refresh = async () => {
    window.clearTimeout(timer.current);
    try {
      const found = await api<Summary[]>('/api/transcription/jobs');
      setList(found);
      if (found.some(working)) timer.current = window.setTimeout(refresh, 1500);
    } catch (e) {
      setList((current) => current ?? []);
      setError(message(e));
    }
  };
  useEffect(() => {
    void refresh();
    return () => window.clearTimeout(timer.current);
  }, []);

  async function start() {
    if (!file) return;
    setStarting(true);
    setError('');
    const form = new FormData();
    form.append('file', file);
    form.append('language', language);
    try {
      const { id } = await api<{ id: string }>('/api/transcription/jobs', { method: 'POST', body: form });
      setSelected(id);
      setFile(null);
      await refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      setStarting(false);
    }
  }

  const current = list?.find((j) => j.id === selected);

  return (
    <section className="page">
      <h1>Transcribe</h1>
      <div className="card">
        <label className="field">
          Audio or video file
          <input key={starting ? 's' : 'i'} type="file" accept="audio/*,video/*,.mkv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="field">
          Language
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="row">
          <button className="primary" disabled={!file || starting} onClick={start}>
            {starting ? 'Uploading…' : 'Transcribe'}
          </button>
        </div>
        <small className="meta">Long files take a while; you can leave this page and come back.</small>
      </div>
      {error && <p className="error">{error}</p>}

      {current && <Viewer key={current.id + current.state} summary={current} />}

      <h2>Your transcripts</h2>
      {list === null && <p className="meta">Loading…</p>}
      {list?.length === 0 && <p className="meta">Nothing transcribed yet.</p>}
      {list?.map((j) => (
        <button key={j.id} className={j.id === selected ? 'nav active' : 'nav'} onClick={() => setSelected(j.id)}>
          {j.title} · {working(j) ? `${j.percent}%` : j.state === 'error' ? 'failed' : (j.detected || j.language).toUpperCase()} ·{' '}
          {new Date(j.created * 1000).toLocaleString()}
        </button>
      ))}
    </section>
  );
}

function Viewer({ summary }: { summary: Summary }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (summary.state === 'done') api<Detail>(`/api/transcription/jobs/${summary.id}`).then(setDetail, () => setDetail(null));
  }, [summary.id, summary.state]);

  if (summary.state === 'error') return <div className="card error">{summary.error}</div>;
  if (summary.state !== 'done')
    return (
      <div className="card">
        <div>{summary.state === 'queued' ? 'Waiting for the previous transcription…' : `Transcribing ${summary.title}…`}</div>
        <progress max={100} value={summary.percent} style={{ width: '100%' }} />
      </div>
    );
  if (!detail?.transcript) return <p className="meta">Loading…</p>;

  const { text, segments } = detail.transcript;
  const copy = () => navigator.clipboard.writeText(text).then(() => setCopied(true));
  const base = `/api/transcription/jobs/${summary.id}/export`;

  return (
    <div className="card">
      <h2 style={{ margin: 0 }}>{summary.title}</h2>
      <div className="row">
        <button className="secondary" onClick={copy}>
          {copied ? 'Copied' : 'Copy text'}
        </button>
        {(['txt', 'srt', 'vtt'] as const).map((fmt) => (
          <a key={fmt} href={apiUrl(`${base}/${fmt}`)} download={`${summary.title}.${fmt}`}>
            Download {fmt.toUpperCase()}
          </a>
        ))}
      </div>
      <div style={{ maxHeight: 420, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {segments.map((s, i) => (
          <div key={i} className="row" style={{ alignItems: 'baseline' }}>
            <span className="meta" style={{ minWidth: 48 }}>
              {clock(s.start)}
            </span>
            <span>{s.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
