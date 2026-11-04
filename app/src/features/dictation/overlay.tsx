import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Check, CircleAlert, Loader2, Square, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { LiveWaveform } from '@/components/ui/live-waveform';
import { applyTheme } from '@/lib/theme';
import '../../styles.css';

const HIDE_AFTER_MS = { done: 4_000, error: 8_000 };
const PASTE_KEY = navigator.platform.startsWith('Mac') ? 'Cmd+V' : 'Ctrl+V';

const action = (name: DictationOverlayAction) => window.voxwell?.dictation.overlayAction(name);

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.floor((now - since) / 1000));
  return <span className="text-destructive shrink-0 text-sm tabular-nums">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}</span>;
}

function Dismiss() {
  return (
    <Button variant="ghost" size="icon-sm" aria-label="Dismiss" title="Dismiss" onClick={() => action('dismiss')}>
      <X />
    </Button>
  );
}

function Overlay() {
  const [status, setStatus] = useState<DictationStatus>(null);

  useEffect(() => {
    const off = window.voxwell?.dictation.onStatus((next) => {
      if (next) applyTheme(); // the theme may have changed in the main window since this one opened
      setStatus(next);
    });
    action('ready');
    return off;
  }, []);

  const phase = status?.phase;
  useEffect(() => {
    if (phase !== 'done' && phase !== 'error') return;
    const timer = window.setTimeout(() => action('dismiss'), HIDE_AFTER_MS[phase]);
    return () => window.clearTimeout(timer);
  }, [status, phase]);

  if (!status) return null;
  return (
    <div className="bg-card text-card-foreground flex h-screen items-center gap-3 overflow-hidden rounded-2xl border px-4">
      {status.phase === 'recording' && (
        <>
          <span className="sr-only" role="status">Recording</span>
          <span aria-hidden className="bg-destructive size-2 shrink-0 rounded-full motion-safe:animate-pulse" />
          <Elapsed since={status.startedAt} />
          <LiveWaveform active deviceId={status.deviceId} height={32} mode="static" className="min-w-0 flex-1" />
          <Button variant="ghost" size="icon-sm" aria-label="Cancel" title="Cancel" onClick={() => action('cancel')}>
            <X />
          </Button>
          <Button variant="destructive" size="icon-sm" aria-label="Stop" title="Stop and transcribe" onClick={() => action('stop')}>
            <Square />
          </Button>
        </>
      )}
      {status.phase === 'transcribing' && (
        <>
          <Loader2 className="text-muted-foreground size-4 shrink-0 motion-safe:animate-spin" />
          <span role="status" className="text-sm">Transcribing…</span>
        </>
      )}
      {status.phase === 'done' && (
        <>
          <Check className="text-primary size-4 shrink-0" />
          <div role="status" className="min-w-0 flex-1">
            <p className="text-sm font-medium">Copied. Press {PASTE_KEY} to paste.</p>
            <p className="text-muted-foreground truncate text-xs">{status.text}</p>
          </div>
          <Dismiss />
        </>
      )}
      {status.phase === 'error' && (
        <>
          <CircleAlert className="text-destructive size-4 shrink-0" />
          <p role="alert" className="line-clamp-2 min-w-0 flex-1 text-sm">{status.message}</p>
          <Dismiss />
        </>
      )}
    </div>
  );
}

applyTheme();
createRoot(document.getElementById('root')!).render(<Overlay />);
