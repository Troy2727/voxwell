import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import {
  AudioPlayerButton,
  AudioPlayerDuration,
  AudioPlayerProgress,
  AudioPlayerProvider,
  AudioPlayerTime,
  useAudioPlayer,
  useAudioPlayerTime,
} from '@/components/ui/audio-player';
import { Button } from '@/components/ui/button';
import { AudioScrubber } from '@/components/ui/waveform';

const BARS = 120;
// Above this the file is not decoded for a waveform (a whole audiobook would take too much memory).
const MAX_WAVEFORM_BYTES = 40 * 1024 * 1024;

/** Peak level per bar, 0..1, decoded from the audio itself. Null while loading, when too large
 *  or while `src` is null. */
function usePeaks(src: string | null) {
  const [peaks, setPeaks] = useState<number[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    setPeaks(null);
    if (!src) return;
    (async () => {
      const res = await fetch(src);
      if (Number(res.headers.get('content-length') ?? 0) > MAX_WAVEFORM_BYTES) return;
      const ctx = new AudioContext();
      try {
        const buffer = await ctx.decodeAudioData(await res.arrayBuffer());
        const data = buffer.getChannelData(0);
        const step = Math.max(1, Math.floor(data.length / BARS));
        const out: number[] = [];
        for (let i = 0; i < BARS; i++) {
          let max = 0;
          for (let j = i * step; j < Math.min((i + 1) * step, data.length); j++) max = Math.max(max, Math.abs(data[j]));
          out.push(max);
        }
        const top = Math.max(...out, 0.01);
        if (!cancelled) setPeaks(out.map((v) => Math.max(0.06, v / top)));
      } finally {
        void ctx.close();
      }
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [src]);
  return peaks;
}

function Player({ src, download, autoPlay, lazy }: Props) {
  const player = useAudioPlayer();
  const time = useAudioPlayerTime();
  const item = { id: src, src };
  // Lazy players (long lists) touch the file only once played.
  const peaks = usePeaks(!lazy || player.isItemActive(src) ? src : null);

  useEffect(() => {
    if (lazy) return;
    // Loads metadata so the duration shows before playing.
    void player.setActiveItem(item).then(() => (autoPlay ? player.play(item) : undefined));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);

  return (
    <div className="bg-muted/30 flex items-center gap-3 rounded-lg border p-3">
      <AudioPlayerButton item={item} variant="default" size="icon" className="size-9 shrink-0 rounded-full" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {peaks ? (
          <AudioScrubber
            data={peaks}
            currentTime={time}
            duration={player.duration ?? 0}
            onSeek={player.seek}
            height={40}
            barWidth={3}
            barGap={1}
            showHandle={false}
          />
        ) : (
          <AudioPlayerProgress className="h-10" />
        )}
        <div className="flex justify-between">
          <AudioPlayerTime className="text-xs" />
          <AudioPlayerDuration className="text-xs" />
        </div>
      </div>
      {download && (
        <Button asChild variant="ghost" size="icon" className="shrink-0" aria-label="Download">
          <a href={src} download={download}>
            <Download />
          </a>
        </Button>
      )}
    </div>
  );
}

interface Props {
  src: string;
  download?: string;
  autoPlay?: boolean;
  lazy?: boolean;
}

/** A playable result: play button, real waveform you can click to seek, time, optional download. */
export function AudioResult(props: Props) {
  return (
    <AudioPlayerProvider>
      <Player {...props} />
    </AudioPlayerProvider>
  );
}
