import { useEffect, useState } from 'react';
import { ArrowRight, FolderOpen } from 'lucide-react';
import { api } from '../api';
import { WaveStage } from '../auth/wave-stage';
import { FEATURES } from '../features';
import { EmptyState, Section } from '@/components/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

interface Project {
  kind: string;
  id: string;
  title: string;
  created: number;
}

const QUICK_START: { id: string; blurb: string }[] = [
  { id: 'voice_cloning', blurb: 'Clone a voice from a few seconds of speech.' },
  { id: 'voice_design', blurb: 'Describe a voice in words and hear it.' },
  { id: 'dubbing', blurb: 'Translate a video, spoken in the original voice.' },
  { id: 'transcription', blurb: 'Turn audio or video into timed text.' },
  { id: 'translation', blurb: 'Speak one language, hear another.' },
  { id: 'agents', blurb: 'Talk to a local AI that answers out loud.' },
];

const feature = (id: string) => FEATURES.find((f) => f.id === id)!;

/** The landing page: a welcome, the main tools one click away, and what you made lately. */
export function HomePage({ name, online, onOpen }: { name?: string; online: boolean | null; onOpen: (id: string) => void }) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [voices, setVoices] = useState<number | null>(null);

  useEffect(() => {
    if (!online) return;
    api<Project[]>('/api/projects/items').then(setProjects, () => setProjects([]));
    api<unknown[]>('/api/voices').then((v) => setVoices(v.length), () => setVoices(null));
  }, [online]);

  const first = name?.split(/[\s@]/)[0];

  return (
    <section className="mx-auto flex w-full max-w-6xl flex-col gap-6 md:gap-8">
      <div className="bg-card grid overflow-hidden rounded-2xl border md:grid-cols-[1.15fr_1fr]">
        <div className="flex flex-col gap-5 p-6 sm:p-8 lg:p-10">
          <p className="text-primary text-xs font-semibold tracking-[0.25em] uppercase">Voxwell studio</p>
          <h1 className="text-3xl leading-tight font-bold tracking-tight sm:text-4xl">
            {first ? `Welcome back, ${first}.` : 'Welcome to Voxwell.'}{' '}
            <span className="text-primary dark:from-cta-from dark:via-cta-via dark:to-cta-to dark:bg-linear-90 dark:bg-clip-text dark:text-transparent">
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
              Dub a video
            </Button>
          </div>
          <p className="text-muted-foreground flex items-center gap-2 text-sm">
            <span className={cn('size-2 shrink-0 rounded-full', online === null ? 'bg-muted-foreground' : online ? 'bg-success' : 'bg-destructive')} />
            {online === null ? 'Connecting…' : online ? 'Running on this computer' : "Voxwell isn't running on this computer"}
          </p>
        </div>
        <div className="hidden p-6 sm:block md:p-8 md:pl-0">
          <WaveStage />
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold tracking-tight">Start something</h2>
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

      <div className="grid gap-6 lg:grid-cols-3">
        <Section
          className="lg:col-span-2"
          title="Recent projects"
          action={
            <Button variant="ghost" size="sm" onClick={() => onOpen('projects')}>
              See all
            </Button>
          }
        >
          {online && projects === null && <Skeleton className="h-24 w-full" />}
          {(!online || projects?.length === 0) && (
            <EmptyState icon={FolderOpen} title="Nothing here yet">
              Speech, stories and audiobooks you make, videos you dub and files you transcribe appear here.
            </EmptyState>
          )}
          {online && !!projects?.length && (
            <ul className="divide-y">
              {projects.slice(0, 5).map((p) => (
                <li key={`${p.kind}-${p.id}`} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                  <Badge variant="secondary" className="capitalize">{p.kind}</Badge>
                  <span className="min-w-0 flex-1 truncate font-medium">{p.title}</span>
                  <span className="text-muted-foreground shrink-0 text-xs">{new Date(p.created * 1000).toLocaleDateString()}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Your studio">
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'Saved voices', value: voices, id: 'voices' },
              { label: 'Projects', value: projects?.length ?? null, id: 'projects' },
            ].map((s) => (
              <button key={s.id} type="button" onClick={() => onOpen(s.id)} className="bg-secondary hover:bg-accent flex flex-col gap-1 rounded-xl border p-4 text-left transition-colors">
                <span className="text-muted-foreground text-xs">{s.label}</span>
                <span className="text-2xl font-bold">{online && s.value !== null ? s.value : '–'}</span>
              </button>
            ))}
          </div>
          <Button variant="outline" className="max-w-full" onClick={() => onOpen('gallery')}>
            Browse ready-made voices
          </Button>
        </Section>
      </div>
    </section>
  );
}
