import { useEffect, useRef, useState } from 'react';
import { Download, FolderOpen, Pencil } from 'lucide-react';
import { toast } from 'sonner';
import { api, apiUrl, sendJson } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ConfirmButton } from '@/components/confirm-button';
import { JobProgress } from '@/components/job-progress';
import { EmptyState, ErrorAlert, message, Muted, Page as PageLayout } from '@/components/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';

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

interface Audiobook extends Base {
  kind: 'audiobook';
  state: Dub['state'] | 'draft' | 'paused';
  step: string;
  percent: number;
  error: string | null;
  chapters: { title: string }[];
  chapters_done: number;
  download_url: string;
}

type Item = Speech | Story | Audiobook | Dub | Transcript;

const KIND_LABELS: Record<Item['kind'], string> = {
  speech: 'Speech', story: 'Story', audiobook: 'Audiobook', dub: 'Dub', transcript: 'Transcript',
};
const PREVIEW_LENGTH = 300;

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
    <PageLayout title="Projects" description="Everything you made, newest first.">
      <ErrorAlert message={error} />
      {items === null && <Skeleton className="h-32 w-full" />}
      {items?.length === 0 && !error && (
        <EmptyState icon={FolderOpen} title="Nothing here yet">
          Speech, stories and audiobooks you make, videos you dub and files you transcribe appear here.
        </EmptyState>
      )}
      {items?.map((item) => (
        <ProjectCard key={`${item.kind}-${item.id}`} item={item} onChanged={refresh} onError={(e) => setError(message(e))} />
      ))}
    </PageLayout>
  );
}

function ProjectCard({ item, onChanged, onError }: { item: Item; onChanged: () => void; onError: (e: unknown) => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);
  const [busy, setBusy] = useState(false);
  const path = `/api/projects/items/${item.kind}/${item.id}`;

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    try {
      await action();
      setEditing(false);
      onChanged();
      toast.success(done);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  const rename = () => run(() => sendJson(path, 'PATCH', { title }), 'Renamed');
  const remove = () => run(() => sendJson(path, 'DELETE'), `Deleted "${item.title}"`);

  return (
    <Card className="gap-3 py-4">
      <CardContent className="flex flex-col gap-3 px-4">
        {editing ? (
          <div className="flex items-center gap-2">
            <Input value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} className="flex-1" autoFocus />
            <Button disabled={busy || !title.trim()} onClick={rename}>Save</Button>
            <Button variant="outline" disabled={busy} onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <h2 className="flex-1 truncate font-semibold">{item.title}</h2>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => { setTitle(item.title); setEditing(true); }}>
              <Pencil /> Rename
            </Button>
            <ConfirmButton title={`Delete "${item.title}"?`} disabled={busy || working(item)} onConfirm={remove}>
              Delete
            </ConfirmButton>
          </div>
        )}
        <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
          <Badge variant="secondary">{KIND_LABELS[item.kind]}</Badge>
          {[item.language.toUpperCase(), item.voice, new Date(item.created * 1000).toLocaleString()].filter(Boolean).join(' · ')}
        </div>

        {item.kind === 'speech' && <SpeechBody item={item} />}
        {item.kind === 'story' && <StoryBody item={item} />}
        {item.kind === 'audiobook' && <AudiobookBody item={item} />}
        {item.kind === 'dub' && <DubBody item={item} />}
        {item.kind === 'transcript' && <TranscriptBody item={item} />}
      </CardContent>
    </Card>
  );
}

function DownloadLink({ href, name, children }: { href: string; name: string; children: React.ReactNode }) {
  return (
    <Button asChild variant="secondary" size="sm">
      <a href={apiUrl(href)} download={name}>
        <Download /> {children}
      </a>
    </Button>
  );
}

function SpeechBody({ item }: { item: Speech }) {
  return (
    <>
      {item.text !== item.title && <Muted>{item.text}</Muted>}
      <AudioResult src={apiUrl(item.audio_url)} download={`${item.title}.wav`} lazy />
    </>
  );
}

function AudiobookBody({ item }: { item: Audiobook }) {
  if (item.state === 'queued' || item.state === 'running' || item.state === 'error') return <Progress item={item} />;
  return (
    <>
      <Muted>
        {item.chapters_done} of {item.chapters.length} chapters rendered
        {item.state === 'paused' && ' · paused; resume it in Audiobook'}
        {item.state === 'draft' && item.chapters_done === 0 && ' · open Audiobook to render it'}
      </Muted>
      {item.chapters_done > 0 && (
        <div>
          <DownloadLink href={item.download_url} name={`${item.title}.zip`}>Download chapters (ZIP)</DownloadLink>
        </div>
      )}
    </>
  );
}

function StoryBody({ item }: { item: Story }) {
  if (item.state !== 'done') return <Progress item={item} />;
  return (
    <>
      <Muted>Speakers: {item.speakers.join(', ')}</Muted>
      <AudioResult src={apiUrl(item.audio_url)} download={`${item.title}.wav`} lazy />
    </>
  );
}

function Progress({ item }: { item: Story | Audiobook | Dub | Transcript }) {
  if (item.state === 'error') return <ErrorAlert message={item.error ?? 'Failed'} />;
  return <JobProgress step={item.step} percent={item.percent} />;
}

function TranscriptBody({ item }: { item: Transcript }) {
  if (item.state !== 'done') return <Progress item={item} />;
  const preview = item.text.length > PREVIEW_LENGTH ? item.text.slice(0, PREVIEW_LENGTH - 1) + '…' : item.text;
  return (
    <>
      <Muted>{preview}</Muted>
      <div className="flex flex-wrap gap-2">
        {(['txt', 'srt', 'vtt'] as const).map((fmt) => (
          <DownloadLink key={fmt} href={item.exports[fmt]} name={`${item.title}.${fmt}`}>
            Download {fmt.toUpperCase()}
          </DownloadLink>
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
      <div className="flex flex-wrap gap-2">
        <DownloadLink href={item.video_url} name={`${item.title}.mp4`}>Download video</DownloadLink>
        <DownloadLink href={item.subtitles_url} name={`${item.title}.srt`}>Download subtitles</DownloadLink>
      </div>
    </>
  );
}
