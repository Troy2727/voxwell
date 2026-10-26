import { useEffect, useRef, useState } from 'react';
import { api, apiUrl, sendJson } from '../../api';

interface Base {
  id: string;
  title: string;
  created: number;
  language: string;
  voice: string;
}

interface Speech extends Base {
  kind: 'speech';
  text: string;
  audio_url: string;
}

interface Dub extends Base {
  kind: 'dub';
  state: 'queued' | 'running' | 'done' | 'error';
  step: string;
  percent: number;
  error: string | null;
  video_url: string;
  subtitles_url: string;
}

interface Transcript extends Base {
  kind: 'transcript';
  state: Dub['state'];
  step: string;
  percent: number;
  error: string | null;
  text: string;
  exports: Record<'txt' | 'srt' | 'vtt', string>;
}

interface Story extends Base {
  kind: 'story';
  state: Dub['state'];
  step: string;
  percent: number;
  error: string | null;
  speakers: string[];
  audio_url: string;
}

type Item = Speech | Story | Dub | Transcript;

const KIND_LABELS: Record<Item['kind'], string> = { speech: 'Speech', story: 'Story', dub: 'Dub', transcript: 'Transcript' };
const PREVIEW_LENGTH = 300;

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const working = (item: Item) => item.kind !== 'speech' && (item.state === 'queued' || item.state === 'running');

export default function Page() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState('');
  const timer = useRef<number | undefined>(undefined);

  const refresh = async () => {
    window.clearTimeout(timer.current);
    try {
      const found = await api<Item[]>('/api/projects/items');
      setItems(found);
      // Keep dubs that are still working up to date.
      if (found.some(working)) timer.current = window.setTimeout(refresh, 2000);
    } catch (e) {
      setItems((current) => current ?? []);
      setError(message(e));
    }
  };
  useEffect(() => {
    void refresh();
    return () => window.clearTimeout(timer.current);
  }, []);

  return (
    <section className="page">
      <h1>Projects</h1>
      {error && <p className="error">{error}</p>}
      {items === null && <p className="meta">Loading…</p>}
      {items?.length === 0 && !error && (
        <div className="card">
          <p>Nothing here yet. Speech and stories you generate, videos you dub and files you transcribe appear here.</p>
        </div>
      )}
      {items?.map((item) => (
        <ProjectCard key={`${item.kind}-${item.id}`} item={item} onChanged={refresh} onError={(e) => setError(message(e))} />
      ))}
    </section>
  );
}

function ProjectCard({ item, onChanged, onError }: { item: Item; onChanged: () => void; onError: (e: unknown) => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [busy, setBusy] = useState(false);
  const path = `/api/projects/items/${item.kind}/${item.id}`;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      setEditing(false);
      onChanged();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  const rename = () => run(() => sendJson(path, 'PATCH', { title }));
  const remove = () => {
    if (window.confirm(`Delete "${item.title}"? This cannot be undone.`)) void run(() => sendJson(path, 'DELETE'));
  };

  return (
    <div className="card">
      {editing ? (
        <div className="row">
          <input value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} style={{ flex: 1 }} autoFocus />
          <button className="primary" disabled={busy || !title.trim()} onClick={rename}>
            Save
          </button>
          <button className="secondary" disabled={busy} onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <h2 style={{ margin: 0 }}>{item.title}</h2>
      )}
      <div className="meta">
        {[KIND_LABELS[item.kind], item.language.toUpperCase(), item.voice, new Date(item.created * 1000).toLocaleString()]
          .filter(Boolean)
          .join(' · ')}
      </div>

      {item.kind === 'speech' && <SpeechBody item={item} />}
      {item.kind === 'story' && <StoryBody item={item} />}
      {item.kind === 'dub' && <DubBody item={item} />}
      {item.kind === 'transcript' && <TranscriptBody item={item} />}

      {!editing && (
        <div className="row">
          <button className="secondary" disabled={busy} onClick={() => { setTitle(item.title); setEditing(true); }}>
            Rename
          </button>
          <button className="secondary danger" disabled={busy || working(item)} onClick={remove}>
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

function SpeechBody({ item }: { item: Speech }) {
  return (
    <>
      {item.text !== item.title && <p className="meta">{item.text}</p>}
      <audio controls preload="none" src={apiUrl(item.audio_url)} />
      <a href={apiUrl(item.audio_url)} download={`${item.title}.wav`}>
        Download WAV
      </a>
    </>
  );
}

function StoryBody({ item }: { item: Story }) {
  if (item.state !== 'done') return <Progress item={item} />;
  return (
    <>
      <p className="meta">Speakers: {item.speakers.join(', ')}</p>
      <audio controls preload="none" src={apiUrl(item.audio_url)} />
      <a href={apiUrl(item.audio_url)} download={`${item.title}.wav`}>
        Download WAV
      </a>
    </>
  );
}

function Progress({ item }: { item: Story | Dub | Transcript }) {
  if (item.state === 'error') return <p className="error">{item.error}</p>;
  return (
    <>
      <div>{item.step}</div>
      <progress max={100} value={item.percent} style={{ width: '100%' }} />
    </>
  );
}

function TranscriptBody({ item }: { item: Transcript }) {
  if (item.state !== 'done') return <Progress item={item} />;
  const preview = item.text.length > PREVIEW_LENGTH ? item.text.slice(0, PREVIEW_LENGTH - 1) + '…' : item.text;
  return (
    <>
      <p className="meta">{preview}</p>
      <div className="row">
        {(['txt', 'srt', 'vtt'] as const).map((fmt) => (
          <a key={fmt} href={apiUrl(item.exports[fmt])} download={`${item.title}.${fmt}`}>
            Download {fmt.toUpperCase()}
          </a>
        ))}
      </div>
    </>
  );
}

function DubBody({ item }: { item: Dub }) {
  if (item.state !== 'done') return <Progress item={item} />;
  return (
    <>
      <video controls preload="none" src={apiUrl(item.video_url)} />
      <div className="row">
        <a href={apiUrl(item.video_url)} download={`${item.title}.mp4`}>
          Download video
        </a>
        <a href={apiUrl(item.subtitles_url)} download={`${item.title}.srt`}>
          Download subtitles
        </a>
      </div>
    </>
  );
}
