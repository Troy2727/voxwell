import { useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowRight, FolderOpen, Languages, LayoutGrid, Pause, Play, Unplug } from 'lucide-react';
import { toast } from 'sonner';
import { api, apiUrl, listVoices, onPhoneOrTablet, voiceSourceLabel, type Voice } from '../api';
import { WaveStage } from '../auth/wave-stage';
import { FEATURES } from '../features';
import { EmptyState, Muted, Section } from '@/components/page';
import { PhoneDictation } from '@/components/phone-dictation';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { INSTALL_URL } from '@/lib/links';
import { cn } from '@/lib/utils';

interface Project {
  kind: string;
  id: string;
  title: string;
  created: number;
  state?: string;
  audio_url?: string;
}

/** A list from the backend: null while loading, 'failed' when the request did not work. */
type Loaded<T> = T[] | null | 'failed';

// The buttons in the hero already lead to cloning and dubbing, so these are the other ways in.
const QUICK_START: { id: string; blurb: string }[] = [
  { id: 'voice_design', blurb: 'Describe a voice in words and hear it.' },
  { id: 'transcription', blurb: 'Turn audio or video into timed text.' },
  { id: 'dictation', blurb: 'Speak and get text, all on this computer.' },
  { id: 'translation', blurb: 'Speak one language, hear another.' },
  { id: 'agents', blurb: 'Talk to a local AI that answers out loud.' },
  { id: 'batch', blurb: 'Dub many videos in one go.' },
];

const SHOWN_VOICES = 3;
const LINK = 'text-foreground underline disabled:opacity-60';

const feature = (id: string) => FEATURES.find((f) => f.id === id)!;

/** "today", "yesterday", "3 days ago"; a plain date once it's a week old. */
function when(created: number) {
  const date = new Date(created * 1000);
  const days = Math.round((new Date(date).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86_400_000);
  return Math.abs(days) < 7 ? new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }).format(days, 'day') : date.toLocaleDateString();
}

/** Plays one clip at a time, and stops when the page goes away. */
function useClip() {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  useEffect(() => () => audio.current?.pause(), []);

  const toggle = (src: string) => {
    audio.current?.pause();
    if (playing === src) {
      setPlaying(null);
      return;
    }
    const clip = new Audio(src);
    const stop = () => setPlaying((now) => (now === src ? null : now));
    clip.onended = stop;
    clip.onerror = () => {
      stop();
      toast.error("Couldn't play that clip.");
    };
    audio.current = clip;
    setPlaying(src);
    void clip.play().catch(() => {}); // A failed load lands in onerror; a pause mid-load is not a failure.
  };
  return { playing, toggle };
}

function PlayButton({ name, src, clip }: { name: string; src: string; clip: ReturnType<typeof useClip> }) {
  const playing = clip.playing === src;
  return (
    <Button variant="ghost" size="icon" className="size-11 shrink-0 md:size-9" aria-label={`${playing ? 'Pause' : 'Play'} ${name}`} onClick={() => clip.toggle(src)}>
      {playing ? <Pause /> : <Play />}
    </Button>
  );
}

/** The landing page: a welcome, the main tools one click away, and what you made lately. */
export function HomePage({ name, online, onOpen, onRetry }: { name?: string; online: boolean | null; onOpen: (id: string) => void; onRetry: () => Promise<boolean> }) {
  const [projects, setProjects] = useState<Loaded<Project>>(null);
  const [voices, setVoices] = useState<Loaded<Voice>>(null);
  const [attempt, setAttempt] = useState(0);
  const [checking, setChecking] = useState(false);
  const clip = useClip();

  useEffect(() => {
    if (!online) return;
    api<Project[]>('/api/projects/items').then(setProjects, () => setProjects('failed'));
    listVoices().then(setVoices, () => setVoices('failed'));
  }, [online, attempt]);

  const first = name?.split(/[\s@]/)[0];

  const reload = () => {
    setProjects(null);
    setVoices(null);
    setAttempt((n) => n + 1);
  };

  const checkAgain = async () => {
    setChecking(true);
    if (await onRetry()) return; // Connected: the shell remounts this page.
    setChecking(false);
    toast.error("Still can't reach Voxwell.");
  };

  const openProject = (p: Project) => {
    window.location.hash = `project-${p.kind}-${p.id}`; // The Projects page scrolls to it.
    onOpen('projects');
  };

  return (
    <section className="mx-auto flex w-full max-w-6xl flex-col gap-6 md:gap-8">
      <div className="bg-card grid overflow-hidden rounded-2xl border md:grid-cols-[1.15fr_1fr]">
        <div className="flex flex-col gap-5 p-6 sm:p-8 lg:p-10">
          <h1 className="text-3xl leading-tight font-bold tracking-tight sm:text-4xl">
            {first ? `Welcome back, ${first}.` : 'Welcome to Voxwell.'}{' '}
            <span className="text-primary">
              What will you make?
            </span>
          </h1>
          <p className="text-muted-foreground max-w-md">Clone and design voices, dub videos, transcribe and talk to voice agents. Every model runs on this computer.</p>
          <div className="flex flex-wrap gap-3">
            <Button size="lg" className="max-w-full" onClick={() => onOpen('voice_cloning')}>
              Clone a voice
              <ArrowRight />
            </Button>
            <Button size="lg" variant="outline" className="max-w-full" onClick={() => onOpen('dubbing')}>
              <Languages />
              Dub a video
            </Button>
          </div>
          <p className="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
            <span className="relative flex size-2 shrink-0">
              {/* A soft "live" ripple while connected; still when offline or with reduced motion. */}
              {online && <span className="bg-success absolute inset-0 animate-ping rounded-full opacity-60 [animation-duration:2s] motion-reduce:hidden" />}
              <span className={cn('relative size-2 rounded-full', online === null ? 'bg-muted-foreground' : online ? 'bg-success' : 'bg-destructive')} />
            </span>
            {online === null ? 'Connecting…' : online ? 'Running on this computer' : onPhoneOrTablet() ? 'Voxwell runs on a computer, not a phone or tablet' : "Voxwell isn't running on this computer"}
            {online === false && !window.voxwell && !onPhoneOrTablet() && (
              <a className={LINK} href={INSTALL_URL} target="_blank" rel="noreferrer">Install it</a>
            )}
            {online === false && !onPhoneOrTablet() && (
              <button type="button" className={LINK} disabled={checking} onClick={() => void checkAgain()}>
                {checking ? 'Checking…' : 'Check again'}
              </button>
            )}
          </p>
          {online === false && window.voxwell && (
            <p className="text-muted-foreground text-sm">Close and reopen Voxwell to restart it.</p>
          )}
        </div>
        <div className="hidden p-6 sm:block md:p-8 md:pl-0">
          <WaveStage />
        </div>
      </div>

      {online === false && onPhoneOrTablet() && <PhoneDictation onOpenDictation={() => onOpen('dictation')} />}

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h2 className="text-lg font-semibold tracking-tight">More ways to start</h2>
          {online === false && <p className="text-muted-foreground text-sm">These need Voxwell running on a computer.</p>}
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {QUICK_START.map(({ id, blurb }) => {
            const f = feature(id);
            return (
              <button
                key={id}
                type="button"
                onClick={() => onOpen(id)}
                className="bg-card hover:border-primary/60 focus-visible:ring-ring/50 group flex items-start gap-4 rounded-xl border p-4 text-left transition-colors outline-none focus-visible:ring-[3px]"
              >
                <span className="from-cta-from/20 to-cta-to/10 text-primary flex size-10 shrink-0 items-center justify-center rounded-lg bg-linear-135">
                  <f.icon className="size-5" />
                </span>
                <span className="flex min-w-0 flex-col gap-1">
                  <span className="flex items-center gap-1.5 font-medium">
                    {f.title}
                    <ArrowRight className="text-primary size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
                  </span>
                  <span className="text-muted-foreground text-sm">{blurb}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Section
          className="lg:col-span-2"
          title="Recent projects"
          action={
            <Button variant="ghost" size="sm" onClick={() => onOpen('projects')}>
              See all
              <ArrowRight />
            </Button>
          }
        >
          {online === false ? (
            <EmptyState icon={Unplug} title="Can't reach your projects">
              Anything you've made stays on your computer and appears here once Voxwell is running.
            </EmptyState>
          ) : projects === null ? (
            <Skeleton className="h-24 w-full" />
          ) : projects === 'failed' ? (
            <EmptyState icon={AlertCircle} title="Couldn't load your projects">
              <button type="button" className={LINK} onClick={reload}>Try again</button>
            </EmptyState>
          ) : projects.length === 0 ? (
            <EmptyState icon={FolderOpen} title="Nothing here yet">
              Speech, stories and audiobooks you make, videos you dub and files you transcribe appear here.
            </EmptyState>
          ) : (
            <ul className="divide-y">
              {projects.slice(0, 5).map((p) => (
                <li key={`${p.kind}-${p.id}`} className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => openProject(p)}
                    className="hover:bg-accent focus-visible:ring-ring/50 -ml-2 flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-lg px-2 py-2 text-left outline-none focus-visible:ring-[3px]"
                  >
                    <Badge variant="secondary" className="capitalize">{p.kind}</Badge>
                    <span className="min-w-0 flex-1 truncate font-medium">{p.title}</span>
                    <span className="text-muted-foreground hidden shrink-0 text-xs sm:inline">{when(p.created)}</span>
                  </button>
                  {p.audio_url && (!p.state || p.state === 'done') ? (
                    <PlayButton name={p.title} src={apiUrl(p.audio_url)} clip={clip} />
                  ) : (
                    <span className="hidden size-11 shrink-0 sm:block md:size-9" /> // Keeps the dates in line; phones hide the dates.
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section
          title="Your voices"
          action={
            <Button variant="ghost" size="sm" onClick={() => onOpen('voices')}>
              See all
              <ArrowRight />
            </Button>
          }
        >
          {online === false ? (
            <Muted>Your saved voices appear here once Voxwell is running.</Muted>
          ) : voices === null ? (
            <Skeleton className="h-24 w-full" />
          ) : voices === 'failed' ? (
            <Muted>Couldn't load your voices. <button type="button" className={LINK} onClick={reload}>Try again</button></Muted>
          ) : voices.length === 0 ? (
            <Muted>No saved voices yet. Clone or design one, or start from a ready-made voice.</Muted>
          ) : (
            <ul className="divide-y">
              {voices.slice(0, SHOWN_VOICES).map((v) => (
                <li key={v.id} className="flex min-h-11 items-center gap-2 py-1">
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate font-medium">{v.name}</span>
                    <span className="text-muted-foreground text-xs">{voiceSourceLabel(v.source)}</span>
                  </span>
                  <PlayButton name={v.name} src={apiUrl(`/api/voices/${v.id}/audio`)} clip={clip} />
                </li>
              ))}
            </ul>
          )}
          <Button variant="outline" className="max-w-full" onClick={() => onOpen('gallery')}>
            <LayoutGrid />
            Browse ready-made voices
          </Button>
        </Section>
      </div>
    </section>
  );
}
