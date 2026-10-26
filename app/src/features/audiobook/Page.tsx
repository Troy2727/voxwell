import { useEffect, useRef, useState } from 'react';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { LANGUAGES } from '../voice_cloning/languages';

interface ChapterInfo {
  title: string;
  chars: number;
  include: boolean;
  status: 'pending' | 'done';
  audio_url: string | null;
}

interface Book {
  id: string;
  title: string;
  created: number;
  language: string;
  voice: string;
  state: 'draft' | 'queued' | 'running' | 'paused' | 'done' | 'error';
  step: string;
  percent: number;
  error: string | null;
  chapters: ChapterInfo[];
  download_url: string;
}

const DEFAULT_VOICE = 'default';
const CHARS_PER_MINUTE = 900; // typical narration speed, for a rough length estimate
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const working = (b: Book) => b.state === 'queued' || b.state === 'running';
const minutes = (chars: number) => Math.max(1, Math.round(chars / CHARS_PER_MINUTE));

export default function Page() {
  const [books, setBooks] = useState<Book[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState('');
  const timer = useRef<number | undefined>(undefined);

  const refresh = async () => {
    window.clearTimeout(timer.current);
    try {
      const found = await api<Book[]>('/api/audiobook/books');
      setBooks(found);
      if (found.some(working)) timer.current = window.setTimeout(refresh, 2000);
    } catch (e) {
      setBooks((current) => current ?? []);
      setError(message(e));
    }
  };
  useEffect(() => {
    void refresh();
    listVoices().then(setVoices, () => setVoices([]));
    return () => window.clearTimeout(timer.current);
  }, []);

  async function importBook(file: File) {
    setImporting(true);
    setError('');
    const form = new FormData();
    form.append('file', file);
    try {
      const book = await api<Book>('/api/audiobook/books', { method: 'POST', body: form });
      setSelected(book.id);
      await refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      setImporting(false);
    }
  }

  const book = books?.find((b) => b.id === selected);

  return (
    <section className="page">
      <h1>Audiobook</h1>
      <div className="card">
        <label className="field">
          Import a book (EPUB, TXT or Markdown)
          <input key={importing ? 'i' : 'r'} type="file" accept=".epub,.txt,.md" disabled={importing}
            onChange={(e) => e.target.files?.[0] && importBook(e.target.files[0])} />
        </label>
        {importing && <span className="meta">Reading the book…</span>}
        <small className="meta">Text files: chapters start at lines like “Chapter 1” or “# Title”.</small>
      </div>
      {error && <p className="error">{error}</p>}

      {book && <BookEditor key={book.id} book={book} voices={voices} onChanged={refresh} />}

      <h2>Your books</h2>
      {books === null && <p className="meta">Loading…</p>}
      {books?.length === 0 && <p className="meta">No books yet. Import one above.</p>}
      {books?.map((b) => (
        <button key={b.id} className={b.id === selected ? 'nav active' : 'nav'} onClick={() => setSelected(b.id)}>
          {b.title} · {b.chapters.filter((c) => c.status === 'done').length}/{b.chapters.length} chapters
          {working(b) && ` · ${b.percent}%`}
        </button>
      ))}
    </section>
  );
}

function BookEditor({ book, voices, onChanged }: { book: Book; voices: Voice[]; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<{ chapter: number; url: string } | null>(null);
  const [previewing, setPreviewing] = useState<number | null>(null);
  const locked = working(book);
  const rendered = book.chapters.some((c) => c.status === 'done');

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await action();
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  const patch = (body: object) => run(() => sendJson(`/api/audiobook/books/${book.id}`, 'PATCH', body));

  const changeSound = (body: { language?: string; voice?: string }) => {
    if (rendered && !window.confirm('Changing the voice or language means every chapter is rendered again. Continue?')) return;
    void patch(body);
  };

  const toggle = (index: number) =>
    patch({ chapters: book.chapters.map((c, i) => ({ include: i === index ? !c.include : c.include })) });

  async function listen(index: number) {
    setPreviewing(index);
    setError('');
    try {
      const res = await sendJson<{ url: string }>(`/api/audiobook/books/${book.id}/preview`, 'POST', { chapter: index });
      setPreview({ chapter: index, url: apiUrl(res.url) });
    } catch (e) {
      setError(message(e));
    } finally {
      setPreviewing(null);
    }
  }

  const included = book.chapters.filter((c) => c.include);
  const left = included.filter((c) => c.status !== 'done');
  const label = book.state === 'paused' || (rendered && left.length > 0) ? 'Resume' : 'Render audiobook';

  return (
    <div className="card">
      <h2 style={{ margin: 0 }}>{book.title}</h2>
      <div className="row">
        <label className="field">
          Language
          <select value={book.language} disabled={locked || busy} onChange={(e) => changeSound({ language: e.target.value })}>
            {LANGUAGES.map(([code, name]) => (
              <option key={code} value={code}>{name}</option>
            ))}
          </select>
        </label>
        <label className="field" style={{ flex: 1 }}>
          Narrator voice
          <select value={book.voice} disabled={locked || busy} onChange={(e) => changeSound({ voice: e.target.value })}>
            <option value={DEFAULT_VOICE}>Default voice</option>
            {voices.map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="meta">
        {included.length} of {book.chapters.length} chapters selected · about {minutes(included.reduce((n, c) => n + c.chars, 0))} min of audio
      </div>
      <div style={{ maxHeight: 360, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {book.chapters.map((c, i) => (
          <div key={i} className="row">
            <input type="checkbox" checked={c.include} disabled={locked || busy} onChange={() => toggle(i)} aria-label={`Include ${c.title}`} />
            <span style={{ flex: 1 }}>{c.title}</span>
            <span className="meta">~{minutes(c.chars)} min</span>
            {c.status === 'done' && c.audio_url ? (
              <a href={apiUrl(c.audio_url)} download={`${String(i + 1).padStart(3, '0')} ${c.title}.wav`}>WAV</a>
            ) : (
              <button className="secondary" disabled={previewing !== null || locked} onClick={() => listen(i)}>
                {previewing === i ? 'Preparing…' : 'Preview'}
              </button>
            )}
          </div>
        ))}
      </div>
      {preview && (
        <div className="field">
          Preview of “{book.chapters[preview.chapter]?.title}”
          <audio controls autoPlay src={preview.url} />
        </div>
      )}

      {locked ? (
        <>
          <div>{book.step}</div>
          <progress max={100} value={book.percent} style={{ width: '100%' }} />
          <small className="meta">Finished chapters are kept even if Voxwell closes; you can resume later.</small>
        </>
      ) : (
        <div className="row">
          <button className="primary" disabled={busy || left.length === 0} onClick={() => run(() => sendJson(`/api/audiobook/books/${book.id}/render`, 'POST'))}>
            {label}
          </button>
          {rendered && <a href={apiUrl(book.download_url)} download={`${book.title}.zip`}>Download all chapters (ZIP)</a>}
        </div>
      )}
      {book.state === 'done' && left.length === 0 && <p className="meta">All selected chapters are rendered.</p>}
      {(book.state === 'error' || book.state === 'paused') && <p className={book.state === 'error' ? 'error' : 'meta'}>{book.error}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
