import { useEffect, useRef, useState } from 'react';
import { Download, Headphones, Play } from 'lucide-react';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { FileDrop } from '@/components/file-drop';
import { JobProgress } from '@/components/job-progress';
import { ErrorAlert, Field, message, Muted, Page as PageLayout, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
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
    <PageLayout title="Audiobook" description="Turn an EPUB, TXT or Markdown book into narrated chapters.">
      <Section title="Import a book" description="Text files: chapters start at lines like “Chapter 1” or “# Title”.">
        <FileDrop
          file={null}
          onFile={(f) => f && importBook(f)}
          accept=".epub,.txt,.md"
          disabled={importing}
          label={importing ? 'Reading the book…' : 'Drop an EPUB, TXT or Markdown file here or click to choose'}
        />
      </Section>
      <ErrorAlert message={error} />

      {book && <BookEditor key={book.id} book={book} voices={voices} onChanged={refresh} />}

      <div className="flex flex-col gap-2">
        <h2 className="text-muted-foreground text-sm font-medium tracking-wide uppercase">Your books</h2>
        {books === null && <Skeleton className="h-12 w-full" />}
        {books?.length === 0 && <Muted>No books yet. Import one above.</Muted>}
        {books?.map((b) => (
          <button
            key={b.id}
            onClick={() => setSelected(b.id)}
            className={cn(
              'hover:bg-accent flex items-center gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-colors',
              b.id === selected && 'border-primary bg-accent',
            )}
          >
            <span className="flex-1 truncate font-medium">{b.title}</span>
            <span className="text-muted-foreground">
              {b.chapters.filter((c) => c.status === 'done').length}/{b.chapters.length} chapters
            </span>
            {working(b) && <Badge>{b.percent}%</Badge>}
          </button>
        ))}
      </div>
    </PageLayout>
  );
}

function BookEditor({ book, voices, onChanged }: { book: Book; voices: Voice[]; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<{ chapter: number; url: string } | null>(null);
  const [previewing, setPreviewing] = useState<number | null>(null);
  // Changing the sound after rendering throws finished chapters away, so ask first.
  const [pending, setPending] = useState<{ language?: string; voice?: string } | null>(null);
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

  const changeSound = (body: { language?: string; voice?: string }) => (rendered ? setPending(body) : void patch(body));

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
    <Section
      title={book.title}
      description={`${included.length} of ${book.chapters.length} chapters selected · about ${minutes(included.reduce((n, c) => n + c.chars, 0))} min of audio`}
    >
      <div className="grid gap-4 sm:grid-cols-[200px_1fr]">
        <Field label="Language">
          <ChoiceSelect options={LANGUAGES} value={book.language} disabled={locked || busy} onChange={(language) => changeSound({ language })} />
        </Field>
        <Field label="Narrator voice">
          <VoiceSelect
            voices={voices}
            value={book.voice === DEFAULT_VOICE ? '' : book.voice}
            disabled={locked || busy}
            onChange={(id) => changeSound({ voice: id || DEFAULT_VOICE })}
          />
        </Field>
      </div>

      <Card className="max-h-[360px] gap-0 overflow-auto py-0">
        <CardContent className="divide-y px-0">
          {book.chapters.map((c, i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-2 text-sm">
              <Checkbox checked={c.include} disabled={locked || busy} onCheckedChange={() => toggle(i)} aria-label={`Include ${c.title}`} />
              <span className="flex-1 truncate">{c.title}</span>
              <span className="text-muted-foreground text-xs">~{minutes(c.chars)} min</span>
              {c.status === 'done' && c.audio_url ? (
                <Button asChild variant="ghost" size="sm">
                  <a href={apiUrl(c.audio_url)} download={`${String(i + 1).padStart(3, '0')} ${c.title}.wav`}>
                    <Download /> WAV
                  </a>
                </Button>
              ) : (
                <Button variant="ghost" size="sm" disabled={previewing !== null || locked} onClick={() => listen(i)}>
                  <Headphones /> {previewing === i ? 'Preparing…' : 'Preview'}
                </Button>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
      {preview && (
        <Field label={`Preview of “${book.chapters[preview.chapter]?.title}”`}>
          <AudioResult src={preview.url} autoPlay />
        </Field>
      )}

      {locked ? (
        <JobProgress step={book.step} percent={book.percent} hint="Finished chapters are kept even if Voxwell closes; you can resume later." />
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={busy || left.length === 0} onClick={() => run(() => sendJson(`/api/audiobook/books/${book.id}/render`, 'POST'))}>
            <Play /> {label}
          </Button>
          {rendered && (
            <Button asChild variant="outline">
              <a href={apiUrl(book.download_url)} download={`${book.title}.zip`}>
                <Download /> Download all chapters (ZIP)
              </a>
            </Button>
          )}
        </div>
      )}
      {book.state === 'done' && left.length === 0 && <Muted>All selected chapters are rendered.</Muted>}
      {book.state === 'error' && <ErrorAlert message={book.error ?? 'Failed'} />}
      {book.state === 'paused' && book.error && <Muted>{book.error}</Muted>}
      <ErrorAlert message={error} />

      <AlertDialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Render every chapter again?</AlertDialogTitle>
            <AlertDialogDescription>Changing the voice or language means every chapter is rendered again.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => pending && void patch(pending)}>Continue</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Section>
  );
}
