import { useEffect, useRef, useState } from 'react';
import { Music } from 'lucide-react';
import { getStatus, listTracks, type MusicStatus, type Settings, type Track } from './api';
import { ComposeSection, DEFAULT_SETTINGS } from './Compose';
import { InstallSection } from './Install';
import { TrackCard } from './TrackCard';
import { EmptyState, ErrorAlert, message, Page as PageLayout, Section } from '@/components/page';
import { Skeleton } from '@/components/ui/skeleton';

const POLL_MS = 2000;

export default function Page() {
  const [status, setStatus] = useState<MusicStatus | null>(null);
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [error, setError] = useState('');
  const compose = useRef<HTMLDivElement>(null);

  const refreshStatus = () => getStatus().then(setStatus, (e) => setError(message(e)));
  const refreshTracks = () => listTracks().then(setTracks, (e) => { setTracks((t) => t ?? []); setError(message(e)); });
  useEffect(() => {
    void refreshStatus();
    void refreshTracks();
  }, []);

  // Follow the install and any queued or generating track until they finish.
  const installing = status?.install.state === 'installing';
  const generating = tracks?.some((t) => t.status === 'queued' || t.status === 'generating') ?? false;
  useEffect(() => {
    if (!installing && !generating) return;
    const timer = window.setInterval(() => {
      if (installing) void refreshStatus();
      if (generating) void refreshTracks();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [installing, generating]);

  const replace = (track: Track) => setTracks((list) => (list ?? []).map((t) => (t.id === track.id ? track : t)));
  const queued = (track: Track) => setTracks((list) => [track, ...(list ?? [])]);
  const reuse = (next: Settings) => {
    setSettings(next);
    compose.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <PageLayout title="Music" description="Make songs with sung lyrics, or instrumentals, from a description. Everything runs on your computer.">
      <ErrorAlert message={error} />
      {status === null && !error && <Skeleton className="h-40 w-full" />}
      {status && !status.installed && <InstallSection status={status} onStarted={refreshStatus} />}
      {status?.installed && (
        <div ref={compose} className="scroll-mt-4">
          <ComposeSection status={status} settings={settings} onChange={setSettings} onQueued={queued} />
        </div>
      )}
      <Section title="Tracks">
        {tracks === null && <Skeleton className="h-24 w-full" />}
        {tracks?.length === 0 && (
          <EmptyState icon={Music} title="No tracks yet">
            Tracks you generate appear here, with their progress while they are being made.
          </EmptyState>
        )}
        {tracks?.map((t) => (
          <TrackCard
            key={t.id}
            track={t}
            onChanged={replace}
            onDeleted={() => setTracks((list) => (list ?? []).filter((x) => x.id !== t.id))}
            onQueued={queued}
            onReuse={reuse}
          />
        ))}
      </Section>
    </PageLayout>
  );
}
