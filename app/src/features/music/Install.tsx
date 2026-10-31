import { useState } from 'react';
import { Download, RotateCcw } from 'lucide-react';
import { installEngine, type MusicStatus } from './api';
import { JobProgress } from '@/components/job-progress';
import { ErrorAlert, message, Muted, Section } from '@/components/page';
import { Button } from '@/components/ui/button';

/** Shown until the music engine is installed: what it is, the button, then live progress. */
export function InstallSection({ status, onStarted }: { status: MusicStatus; onStarted: () => void }) {
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const { install } = status;

  async function start() {
    setStarting(true);
    setError('');
    try {
      await installEngine();
      onStarted();
    } catch (e) {
      setError(message(e));
    } finally {
      setStarting(false);
    }
  }

  return (
    <Section
      title="Install the music engine"
      description="Music runs on your computer with ACE-Step 1.5 (MIT licensed). It installs once: about 6 GB of packages and a 6 GB model."
    >
      {install.state === 'installing' ? (
        <JobProgress step={install.step} percent={install.percent} hint={install.detail || 'Keep Voxwell open; you can use other pages meanwhile.'} />
      ) : (
        <>
          {install.state === 'failed' && <ErrorAlert message={install.error} />}
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={start} disabled={starting}>
              {install.state === 'failed' ? <RotateCcw /> : <Download />}
              {install.state === 'failed' ? 'Try again' : 'Install music engine'}
            </Button>
            <Muted>Needs about 15 GB of free disk space.</Muted>
          </div>
        </>
      )}
      <ErrorAlert message={error} />
    </Section>
  );
}
