import { useEffect, useMemo, useRef, useState } from 'react';
import { Copy, Download, FileAudio, FileText } from 'lucide-react';
import { api, apiUrl } from '../../api';
import { ChoiceSelect } from '@/components/choice-select';
import { FileDrop } from '@/components/file-drop';
import { JobProgress } from '@/components/job-progress';
import { EmptyState, ErrorAlert, Field, message, Page as PageLayout, Section } from '@/components/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type CharacterAlignmentResponseModel,
  TranscriptViewerAudio,
  TranscriptViewerContainer,
  TranscriptViewerPlayPauseButton,
  TranscriptViewerScrubBar,
  TranscriptViewerWords,
} from '@/components/ui/transcript-viewer';
import { cn } from '@/lib/utils';
import { AlignPanel } from './AlignPanel';

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

const AUTO = 'auto';
const LANGUAGES: [string, string][] = [
  [AUTO, 'Auto-detect'], ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'],
  ['it', 'Italian'], ['pt', 'Portuguese'], ['nl', 'Dutch'], ['ru', 'Russian'], ['zh', 'Chinese'],
  ['ja', 'Japanese'], ['ko', 'Korean'], ['ar', 'Arabic'], ['hi', 'Hindi'], ['tr', 'Turkish'],
];

const working = (j: Summary) => j.state === 'queued' || j.state === 'running';
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

/** Whisper gives times per segment (about a sentence), so characters inside a segment are spread
 *  evenly over its duration: the highlight follows the voice closely but not exactly per word. */
function alignmentFrom(segments: Segment[]): CharacterAlignmentResponseModel {
  const characters: string[] = [];
  const starts: number[] = [];
  const ends: number[] = [];
  segments.forEach((s, i) => {
    const chars = Array.from(s.text);
    const step = (s.end - s.start) / Math.max(chars.length, 1);
    chars.forEach((c, j) => {
      characters.push(c);
      starts.push(s.start + j * step);
      ends.push(s.start + (j + 1) * step);
    });
    if (i < segments.length - 1) {
      characters.push(' ');
      starts.push(s.end);
      ends.push(s.end);
    }
  });
  return { characters, characterStartTimesSeconds: starts, characterEndTimesSeconds: ends };
}

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState(AUTO);
  const [starting, setStarting] = useState(false);
  const [list, setList] = useState<Summary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  // Files picked on this computer, by transcript: the backend deletes the upload once it is
  // transcribed, so play-along uses the local file and nothing is uploaded twice.
  const [media, setMedia] = useState<Record<string, File>>({});
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
    form.append('language', language === AUTO ? '' : language);
    try {
      const { id } = await api<{ id: string }>('/api/transcription/jobs', { method: 'POST', body: form });
      setSelected(id);
      setMedia((m) => ({ ...m, [id]: file }));
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
    <PageLayout title="Transcribe" description="Turn audio or video into text with timestamps. Export as TXT, SRT or VTT.">
      <Section title="New transcript" description="Long files take a while; you can leave this page and come back.">
        <FileDrop file={file} onFile={setFile} accept="audio/*,video/*,.mkv" disabled={starting} />
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Language" className="w-full sm:w-56">
            <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} />
          </Field>
          <Button disabled={!file || starting} onClick={start}>
            <FileText /> {starting ? 'Uploading…' : 'Transcribe'}
          </Button>
        </div>
      </Section>
      <ErrorAlert message={error} />

      <AlignPanel />

      {current && (
        <Viewer
          key={current.id + current.state}
          summary={current}
          media={media[current.id]}
          onMedia={(f) => setMedia((m) => ({ ...m, [current.id]: f }))}
        />
      )}

      <div className="flex flex-col gap-2">
        <h2 className="text-muted-foreground text-sm font-medium tracking-wide uppercase">Your transcripts</h2>
        {list === null && <Skeleton className="h-12 w-full" />}
        {list?.length === 0 && <EmptyState icon={FileText} title="Nothing transcribed yet">Your transcripts are listed here.</EmptyState>}
        {list?.map((j) => (
          <button
            key={j.id}
            onClick={() => setSelected(j.id)}
            className={cn(
              'hover:bg-accent flex items-center gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-colors',
              j.id === selected && 'border-primary bg-accent',
            )}
          >
            <span className="flex-1 truncate font-medium">{j.title}</span>
            <span className="text-muted-foreground text-xs">{new Date(j.created * 1000).toLocaleString()}</span>
            {working(j) ? (
              <Badge>{j.percent}%</Badge>
            ) : j.state === 'error' ? (
              <Badge variant="destructive">failed</Badge>
            ) : (
              <Badge variant="secondary">{(j.detected || j.language).toUpperCase()}</Badge>
            )}
          </button>
        ))}
      </div>
    </PageLayout>
  );
}

function Viewer({ summary, media, onMedia }: { summary: Summary; media?: File; onMedia: (f: File) => void }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [copied, setCopied] = useState(false);
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const alignment = useMemo(() => (detail?.transcript ? alignmentFrom(detail.transcript.segments) : null), [detail]);

  // The URL is created and revoked by the same effect run, so a remount never keeps a dead URL.
  useEffect(() => {
    if (!media) return setMediaUrl(null);
    const url = URL.createObjectURL(media);
    setMediaUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [media]);

  useEffect(() => {
    if (summary.state === 'done') api<Detail>(`/api/transcription/jobs/${summary.id}`).then(setDetail, () => setDetail(null));
  }, [summary.id, summary.state]);

  if (summary.state === 'error') return <ErrorAlert message={summary.error ?? 'Failed'} />;
  if (summary.state !== 'done')
    return (
      <Section title={summary.title}>
        <JobProgress
          step={summary.state === 'queued' ? 'Waiting for the previous transcription…' : `Transcribing ${summary.title}…`}
          percent={summary.percent}
        />
      </Section>
    );
  if (!detail?.transcript || !alignment) return <Skeleton className="h-40 w-full" />;

  const { text, segments } = detail.transcript;
  const copy = () => navigator.clipboard.writeText(text).then(() => setCopied(true));
  const base = `/api/transcription/jobs/${summary.id}/export`;

  return (
    <Section
      title={summary.title}
      action={
        <Button variant="outline" size="sm" onClick={copy}>
          <Copy /> {copied ? 'Copied' : 'Copy text'}
        </Button>
      }
    >
      <div className="flex flex-wrap gap-2">
        {(['txt', 'srt', 'vtt'] as const).map((fmt) => (
          <Button key={fmt} asChild variant="secondary" size="sm">
            <a href={apiUrl(`${base}/${fmt}`)} download={`${summary.title}.${fmt}`}>
              <Download /> Download {fmt.toUpperCase()}
            </a>
          </Button>
        ))}
      </div>

      {mediaUrl ? (
        <TranscriptViewerContainer
          audioSrc={mediaUrl}
          audioType={(media?.type || 'audio/mpeg') as 'audio/mpeg'}
          alignment={alignment}
          className="bg-muted/30 rounded-lg border"
        >
          <TranscriptViewerAudio className="hidden" />
          <TranscriptViewerWords className="max-h-[360px] overflow-auto text-sm leading-relaxed" />
          <div className="flex items-center gap-3">
            <TranscriptViewerPlayPauseButton className="rounded-full" />
            <TranscriptViewerScrubBar className="flex-1" />
          </div>
        </TranscriptViewerContainer>
      ) : (
        <>
          <PlayAlong onMedia={onMedia} />
          <div className="flex max-h-[420px] flex-col gap-1.5 overflow-auto">
            {segments.map((s, i) => (
              <div key={i} className="flex items-baseline gap-3 text-sm">
                <span className="text-muted-foreground w-12 shrink-0 text-xs tabular-nums">{clock(s.start)}</span>
                <span>{s.text}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </Section>
  );
}

/** Pick the original file from this computer to play it with the words highlighted. */
function PlayAlong({ onMedia }: { onMedia: (f: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="bg-muted/30 flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-sm">
      <FileAudio className="text-muted-foreground size-4" />
      <span className="text-muted-foreground flex-1">Open the original file to play it with the words highlighted. It stays on this computer.</span>
      <Button variant="outline" size="sm" onClick={() => input.current?.click()}>
        Play along…
      </Button>
      <input ref={input} type="file" accept="audio/*,video/*,.mkv" hidden onChange={(e) => e.target.files?.[0] && onMedia(e.target.files[0])} />
    </div>
  );
}
