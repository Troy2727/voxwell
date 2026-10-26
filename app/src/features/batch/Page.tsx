import { useEffect, useRef, useState } from 'react';
import { Eye, EyeOff, FileVideo, Languages, X } from 'lucide-react';
import { api, listVoices, sendJson, type Voice } from '../../api';
import { ChoiceSelect } from '@/components/choice-select';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, Field, message, Muted, Page as PageLayout, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
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

const ORIGINAL = 'original';

export default function Page() {
  const [voices, setVoices] = useState<Voice[]>([]);
  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
  }, []);

  return (
    <PageLayout title="Batch dub" description="Dub many videos in one go, or dub every new video that lands in a folder.">
      <Queue voices={voices} />
      <WatchFolder voices={voices} />
    </PageLayout>
  );
}

function Settings({ voices, language, setLanguage, voice, setVoice, disabled }: {
  voices: Voice[];
  language: string;
  setLanguage: (v: string) => void;
  voice: string;
  setVoice: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Target language">
        <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} disabled={disabled} />
      </Field>
      <Field label="Voice">
        <VoiceSelect
          voices={voices}
          value={voice === ORIGINAL ? '' : voice}
          onChange={(id) => setVoice(id || ORIGINAL)}
          disabled={disabled}
          defaultLabel="Original speaker"
          defaultDescription="Clone the voice in each video"
        />
      </Field>
    </div>
  );
}

/** One file's line in a list: name on the left, its state on the right, an optional bar below. */
function FileRow({ name, children, percent }: { name: string; children: React.ReactNode; percent?: number }) {
  return (
    <div className="flex flex-col gap-1.5 py-2">
      <div className="flex items-center gap-3 text-sm">
        <FileVideo className="text-muted-foreground size-4 shrink-0" />
        <span className="flex-1 truncate">{name}</span>
        {children}
      </div>
      {percent !== undefined && <Progress value={percent} className="h-1" />}
    </div>
  );
}

function Queue({ voices }: { voices: Voice[] }) {
  const [files, setFiles] = useState<File[]>([]);
  const [language, setLanguage] = useState('es');
  const [voice, setVoice] = useState(ORIGINAL);
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
    <Section title="Dub several videos" description="Dubs run one at a time. You can leave this page; finished dubs appear in Projects.">
      <FileDrop
        file={null}
        multiple
        onFiles={(picked) => setFiles((current) => [...current, ...picked])}
        accept="video/*,.mkv"
        disabled={busy}
        label="Drop videos here or click to choose"
      />
      {files.length > 0 && (
        <div className="divide-y rounded-lg border px-3">
          {files.map((f, i) => (
            <FileRow key={`${f.name}-${i}`} name={f.name}>
              <Button variant="ghost" size="icon" className="size-7" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                <X />
              </Button>
            </FileRow>
          ))}
        </div>
      )}
      <Settings voices={voices} language={language} setLanguage={setLanguage} voice={voice} setVoice={setVoice} />
      <div>
        <Button disabled={busy || files.length === 0} onClick={start}>
          <Languages /> {busy ? 'Uploading…' : files.length > 1 ? `Dub ${files.length} videos` : 'Dub'}
        </Button>
      </div>
      <ErrorAlert message={error} />
      {rejected.map((r) => (
        <ErrorAlert key={r.name} message={`${r.name}: ${r.error}`} />
      ))}
      {queued.length > 0 && (
        <div className="divide-y rounded-lg border px-3">
          {queued.map((j) => {
            const s = statuses[j.id];
            return (
              <FileRow key={j.id} name={j.name} percent={s?.state === 'running' ? s.percent : undefined}>
                {!s ? <Badge variant="secondary">…</Badge>
                  : s.state === 'done' ? <Badge className="bg-success text-white">Done</Badge>
                  : s.state === 'error' ? <span className="text-destructive text-xs">{s.error}</span>
                  : <span className="text-muted-foreground text-xs">{s.step} {s.state === 'running' && `${s.percent}%`}</span>}
              </FileRow>
            );
          })}
        </div>
      )}
    </Section>
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
  const [voice, setVoice] = useState(ORIGINAL);
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
    <Section
      title="Watch a folder"
      description={`New videos added to the folder are dubbed automatically and saved in a “${state?.output_folder ?? 'dubbed'}” folder inside it. Videos already there when you start are skipped.`}
      action={state?.enabled ? <Badge className="bg-success text-white">Watching</Badge> : <Badge variant="secondary">Off</Badge>}
    >
      <Field label="Folder" htmlFor="watch-folder">
        <Input id="watch-folder" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="C:\Users\you\Videos\To dub" disabled={state?.enabled} />
      </Field>
      <Settings voices={voices} language={language} setLanguage={setLanguage} voice={voice} setVoice={setVoice} disabled={state?.enabled} />
      <div className="flex flex-wrap items-center gap-3">
        {state?.enabled ? (
          <Button variant="outline" disabled={busy} onClick={() => save(false)}><EyeOff /> Stop watching</Button>
        ) : (
          <Button disabled={busy || !folder.trim()} onClick={() => save(true)}><Eye /> Start watching</Button>
        )}
        {state?.enabled && <Muted>Watching · {state.skipped} existing video(s) skipped</Muted>}
      </div>
      <ErrorAlert message={error} />
      <ErrorAlert message={state?.problem ?? ''} />
      {state && state.files.length > 0 && (
        <div className="divide-y rounded-lg border px-3">
          {state.files.map((f) => (
            <FileRow key={f.name} name={f.name} percent={f.status === 'dubbing' ? f.percent ?? 0 : undefined}>
              <span className={f.status === 'failed' ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>
                {f.status === 'failed' ? f.error : f.status === 'dubbing' && f.step ? `${f.step} ${f.percent ?? 0}%` : STATUS_LABELS[f.status]}
              </span>
            </FileRow>
          ))}
        </div>
      )}
    </Section>
  );
}
