import { useEffect, useState } from 'react';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { LANGUAGES } from '../voice_cloning/languages';

const TOOLS = [
  { id: 'convert', title: 'Convert voice', hint: 'Re-speak a recording in one of your saved voices. The words and timing stay the same.' },
  { id: 'compare', title: 'Compare voices', hint: 'Hear the same sentence in several voices, side by side.' },
  { id: 'fit', title: 'Fit length', hint: 'Speed audio up or slow it down to an exact length, without changing the pitch.' },
  { id: 'probe', title: 'File info', hint: 'See the format, length and streams of an audio or video file.' },
] as const;

type ToolId = (typeof TOOLS)[number]['id'];
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Page() {
  const [tool, setTool] = useState<ToolId>('convert');
  const [voices, setVoices] = useState<Voice[]>([]);
  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
  }, []);
  const current = TOOLS.find((t) => t.id === tool)!;

  return (
    <section className="page">
      <h1>Tools</h1>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {TOOLS.map((t) => (
          <button key={t.id} className={t.id === tool ? 'nav active' : 'nav'} onClick={() => setTool(t.id)}>
            {t.title}
          </button>
        ))}
      </div>
      <div className="card">
        <h2 style={{ margin: 0 }}>{current.title}</h2>
        <p className="meta" style={{ margin: 0 }}>{current.hint}</p>
        {tool === 'convert' && <Convert voices={voices} />}
        {tool === 'compare' && <Compare voices={voices} />}
        {tool === 'fit' && <Fit />}
        {tool === 'probe' && <Probe />}
      </div>
    </section>
  );
}

function Result({ url, name }: { url: string; name: string }) {
  return (
    <>
      <audio controls src={apiUrl(url)} />
      <a href={apiUrl(url)} download={name}>Download WAV</a>
    </>
  );
}

function VoiceSelect({ voices, value, onChange, allowDefault = false }: {
  voices: Voice[];
  value: string;
  onChange: (v: string) => void;
  allowDefault?: boolean;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {allowDefault ? <option value="">Default voice</option> : <option value="">Choose a voice…</option>}
      {voices.map((v) => (
        <option key={v.id} value={v.id}>{v.name}</option>
      ))}
    </select>
  );
}

function Convert({ voices }: { voices: Voice[] }) {
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
      <label className="field">
        Recording (WAV, MP3, FLAC or OGG)
        <input type="file" accept=".wav,.mp3,.flac,.ogg,audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        New voice
        <VoiceSelect voices={voices} value={voice} onChange={setVoice} />
      </label>
      {voices.length === 0 && <small className="meta">Add a voice in Voice cloning, Voice design or Gallery first.</small>}
      <div className="row">
        <button className="primary" disabled={busy || !file || !voice} onClick={run}>
          {busy ? 'Converting…' : 'Convert'}
        </button>
        {busy && <span className="meta">The first time downloads the conversion model.</span>}
      </div>
      {error && <p className="error">{error}</p>}
      {url && <Result url={url} name="converted.wav" />}
    </>
  );
}

const MAX_COMPARE = 4;

function Compare({ voices }: { voices: Voice[] }) {
  const [text, setText] = useState('The quick brown fox jumps over the lazy dog.');
  const [language, setLanguage] = useState('en');
  const [chosen, setChosen] = useState<string[]>(['', '']);
  const [results, setResults] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState('');

  async function run() {
    setError('');
    setResults({});
    // One voice at a time, so each result appears as soon as it is ready.
    for (const [i, voice_id] of chosen.entries()) {
      setBusy(i);
      try {
        const res = await sendJson<{ url: string }>('/api/tools/speak', 'POST', { text, language, voice_id: voice_id || null });
        setResults((r) => ({ ...r, [i]: res.url }));
      } catch (e) {
        setError(message(e));
        break;
      }
    }
    setBusy(null);
  }

  const name = (id: string) => voices.find((v) => v.id === id)?.name ?? 'Default voice';

  return (
    <>
      <label className="field">
        Text
        <textarea rows={2} maxLength={300} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <label className="field">
        Language
        <select value={language} onChange={(e) => setLanguage(e.target.value)}>
          {LANGUAGES.map(([code, label]) => (
            <option key={code} value={code}>{label}</option>
          ))}
        </select>
      </label>
      {chosen.map((voice, i) => (
        <div key={i} className="field">
          Voice {i + 1}
          <div className="row">
            <VoiceSelect voices={voices} value={voice} allowDefault onChange={(v) => setChosen(chosen.map((c, j) => (j === i ? v : c)))} />
            {chosen.length > 2 && (
              <button className="secondary" disabled={busy !== null} onClick={() => setChosen(chosen.filter((_, j) => j !== i))}>
                Remove
              </button>
            )}
          </div>
          {busy === i && <span className="meta">Speaking…</span>}
          {results[i] && <audio controls src={apiUrl(results[i])} aria-label={name(voice)} />}
        </div>
      ))}
      <div className="row">
        {chosen.length < MAX_COMPARE && (
          <button className="secondary" disabled={busy !== null} onClick={() => setChosen([...chosen, ''])}>
            Add a voice
          </button>
        )}
        <button className="primary" disabled={busy !== null || !text.trim()} onClick={run}>
          {busy !== null ? 'Comparing…' : 'Compare'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </>
  );
}

function Fit() {
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
      <label className="field">
        Audio (WAV, MP3, FLAC or OGG)
        <input type="file" accept=".wav,.mp3,.flac,.ogg,audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        New length in seconds
        <input type="number" min={0.1} step={0.1} value={seconds} onChange={(e) => setSeconds(e.target.value)} placeholder="e.g. 12.5" />
      </label>
      <div className="row">
        <button className="primary" disabled={busy || !file || !(Number(seconds) > 0)} onClick={run}>
          {busy ? 'Fitting…' : 'Fit'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <>
          <p className="meta">Was {result.original_seconds.toFixed(2)} s, now {Number(seconds).toFixed(2)} s.</p>
          <Result url={result.url} name="fitted.wav" />
        </>
      )}
    </>
  );
}

interface ProbeInfo {
  format: string | null;
  duration: number | null;
  size: number | null;
  bit_rate: number | null;
  streams: { type: string; codec: string; sample_rate?: number; channels?: number; width?: number; height?: number; fps?: number; language?: string }[];
}

const megabytes = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`;

function Probe() {
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
      <label className="field">
        Audio or video file
        <input type="file" accept="audio/*,video/*,.mkv" disabled={busy} onChange={(e) => e.target.files?.[0] && run(e.target.files[0])} />
      </label>
      {busy && <p className="meta">Reading…</p>}
      {error && <p className="error">{error}</p>}
      {info && (
        <div className="field">
          <span>{info.format}</span>
          <span>
            {info.duration !== null && `${info.duration.toFixed(2)} s`}
            {info.size !== null && ` · ${megabytes(info.size)}`}
            {info.bit_rate !== null && ` · ${Math.round(info.bit_rate / 1000)} kb/s`}
          </span>
          {info.streams.map((s, i) => (
            <span key={i} className="meta">
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
