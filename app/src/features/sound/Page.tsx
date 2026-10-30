import { useEffect, useState } from 'react';
import { KeyRound, Save, Sparkles, Trash2, Volume2 } from 'lucide-react';
import { toast } from 'sonner';
import { api, apiUrl, sendJson } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ConfirmButton } from '@/components/confirm-button';
import { EmptyState, ErrorAlert, Field, message, Muted, Page as PageLayout, Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';

interface Status {
  installed: boolean;
  token_set: boolean;
  model: string;
  model_url: string;
}

interface Sound {
  id: string;
  prompt: string;
  duration: number;
  seed: number;
  steps: number;
  created: number;
  url: string;
}

const MAX_PROMPT = 500;

export default function Page() {
  const [status, setStatus] = useState<Status | null>(null);
  const [history, setHistory] = useState<Sound[] | null>(null);
  const [error, setError] = useState('');

  const refreshStatus = () => api<Status>('/api/sound/status').then(setStatus, (e) => setError(message(e)));
  const refreshHistory = () =>
    api<Sound[]>('/api/sound/history').then(setHistory, (e) => {
      setHistory([]);
      setError(message(e));
    });
  useEffect(() => {
    void refreshStatus();
    void refreshHistory();
  }, []);

  return (
    <PageLayout title="Sound effects" description="Describe a sound and generate it on your computer: ambience, impacts, foley, short music loops.">
      <ErrorAlert message={error} />
      {status === null && !error && <Skeleton className="h-32 w-full" />}
      {status && <TokenSection status={status} onChanged={refreshStatus} onError={(e) => setError(message(e))} />}
      <GenerateSection
        status={status}
        onDone={(sound) => {
          setHistory((h) => [sound, ...(h ?? [])]);
          void refreshStatus();
        }}
      />
      <Section title="History">
        {history === null && <Skeleton className="h-24 w-full" />}
        {history?.length === 0 && (
          <EmptyState icon={Volume2} title="No sounds yet">
            Sounds you generate are saved here.
          </EmptyState>
        )}
        {history?.map((s) => (
          <HistoryItem
            key={s.id}
            sound={s}
            onDeleted={() => setHistory((h) => (h ?? []).filter((x) => x.id !== s.id))}
            onError={(e) => setError(message(e))}
          />
        ))}
      </Section>
    </PageLayout>
  );
}

function TokenSection({ status, onChanged, onError }: { status: Status; onChanged: () => void; onError: (e: unknown) => void }) {
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    try {
      await action();
      setToken('');
      onChanged();
      toast.success(done);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  if (status.token_set) {
    return (
      <Section title="Hugging Face access" description="A token is set. It is stored on this computer and never shown again.">
        <div className="flex items-center gap-2">
          <KeyRound className="text-muted-foreground size-4" />
          <Muted className="flex-1">
            Make sure you have accepted the terms on the{' '}
            <a className="underline" href={status.model_url} target="_blank" rel="noreferrer">model page</a>.
          </Muted>
          <ConfirmButton
            title="Remove the saved token?"
            description="Generating sounds will stop working until you save a token again (or set HF_TOKEN)."
            confirmLabel="Remove"
            disabled={busy}
            onConfirm={() => run(() => sendJson('/api/sound/token', 'DELETE'), 'Token removed')}
          >
            <Trash2 /> Remove token
          </ConfirmButton>
        </div>
      </Section>
    );
  }
  return (
    <Section
      title="Set up Hugging Face access"
      description="Stable Audio Open is a gated model. Sound effects need a free Hugging Face account that has accepted its terms."
    >
      <ol className="text-muted-foreground list-decimal space-y-1 pl-5 text-sm">
        <li>
          Open the <a className="text-foreground underline" href={status.model_url} target="_blank" rel="noreferrer">model page</a> and accept the terms.
        </li>
        <li>
          Create a token with read access at{' '}
          <a className="text-foreground underline" href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">huggingface.co/settings/tokens</a>.
        </li>
        <li>Paste it below. You can also set the HF_TOKEN environment variable instead.</li>
      </ol>
      <Field label="Access token" htmlFor="sound-token">
        <div className="flex gap-2">
          <Input
            id="sound-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="hf_…"
            className="flex-1"
          />
          <Button disabled={busy || !token.trim()} onClick={() => run(() => sendJson('/api/sound/token', 'PUT', { token }), 'Token saved')}>
            <Save /> Save token
          </Button>
        </div>
      </Field>
    </Section>
  );
}

function GenerateSection({ status, onDone }: { status: Status | null; onDone: (sound: Sound) => void }) {
  const [prompt, setPrompt] = useState('');
  const [duration, setDuration] = useState(10);
  const [seed, setSeed] = useState('');
  const [steps, setSteps] = useState(100);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [latest, setLatest] = useState<Sound | null>(null);

  async function generate() {
    setBusy(true);
    setError('');
    setLatest(null);
    try {
      const sound = await sendJson<Sound>('/api/sound/generate', 'POST', {
        prompt,
        duration,
        steps,
        seed: seed.trim() === '' ? null : Number(seed),
      });
      setLatest(sound);
      onDone(sound);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  const seedValid = seed.trim() === '' || (Number.isInteger(Number(seed)) && Number(seed) >= 0);
  const ready = prompt.trim() !== '' && duration >= 1 && duration <= 30 && steps >= 10 && steps <= 250 && seedValid;
  return (
    <Section title="Generate" description={status && !status.installed ? 'The first sound downloads the model (about 5 GB), which takes a while.' : undefined}>
      <Field label="Description" htmlFor="sound-prompt" hint={`${prompt.length} / ${MAX_PROMPT}`}>
        <Textarea
          id="sound-prompt"
          rows={3}
          maxLength={MAX_PROMPT}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Rain on a tin roof with distant thunder"
        />
      </Field>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Length (seconds)" htmlFor="sound-duration" hint="1 to 30">
          <Input id="sound-duration" type="number" min={1} max={30} step={1} value={duration} onChange={(e) => setDuration(Number(e.target.value))} />
        </Field>
        <Field label="Seed (optional)" htmlFor="sound-seed" hint="Reuse a seed to repeat a result">
          <Input id="sound-seed" inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder="Random" aria-invalid={!seedValid} />
        </Field>
        <Field label="Quality steps" htmlFor="sound-steps" hint="10 to 250; fewer is faster">
          <Input id="sound-steps" type="number" min={10} max={250} step={10} value={steps} onChange={(e) => setSteps(Number(e.target.value))} />
        </Field>
      </div>
      <div className="flex items-center gap-3">
        <Button disabled={busy || !ready || status?.token_set === false} onClick={generate}>
          <Sparkles /> {busy ? 'Generating…' : 'Generate'}
        </Button>
        {busy && <Muted>This can take several minutes without a GPU. Keep this page open.</Muted>}
        {status?.token_set === false && <Muted>Save a Hugging Face token above first.</Muted>}
      </div>
      <ErrorAlert message={error} />
      {latest && <AudioResult src={apiUrl(latest.url)} download="voxwell-sound.wav" autoPlay />}
    </Section>
  );
}

function HistoryItem({ sound, onDeleted, onError }: { sound: Sound; onDeleted: () => void; onError: (e: unknown) => void }) {
  async function remove() {
    try {
      await sendJson(`/api/sound/history/${sound.id}`, 'DELETE');
      onDeleted();
      toast.success('Deleted');
    } catch (e) {
      onError(e);
    }
  }
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="break-words font-medium">{sound.prompt}</p>
          <Muted className="text-xs">
            {sound.duration}s · seed {sound.seed} · {sound.steps} steps · {new Date(sound.created * 1000).toLocaleString()}
          </Muted>
        </div>
        <ConfirmButton title="Delete this sound?" onConfirm={remove}>
          <Trash2 /> Delete
        </ConfirmButton>
      </div>
      <AudioResult src={apiUrl(sound.url)} download={`voxwell-sound-${sound.seed}.wav`} lazy />
    </div>
  );
}
