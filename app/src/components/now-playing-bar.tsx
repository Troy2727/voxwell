import { useEffect, useRef, useState } from 'react';
import { AudioLines, X } from 'lucide-react';
import { AudioResult } from '@/components/audio-result';
import { Button } from '@/components/ui/button';
import { closeBar, useNowPlaying } from '@/lib/now-playing';

/** The Now playing bar: one clip, docked at the bottom, playing on while the user changes pages. */
export function NowPlayingBar() {
  const item = useNowPlaying();
  const box = useRef<HTMLDivElement>(null);
  const [failedNonce, setFailedNonce] = useState<number | null>(null); // the clip that couldn't play
  const nonce = item?.nonce;

  useEffect(() => {
    const node = box.current;
    if (!node) return;
    const onError = (e: Event) => {
      if (e.target instanceof HTMLAudioElement) setFailedNonce(nonce ?? null);
    };
    node.addEventListener('error', onError, true); // a media error doesn't bubble; capture sees it
    return () => node.removeEventListener('error', onError, true);
  }, [nonce]);

  if (!item) return null;
  const title = item.title.replace(/\s+/g, ' ').trim();
  return (
    <div role="region" aria-label="Now playing" className="bg-background/80 sticky bottom-0 z-10 border-t px-4 py-2 backdrop-blur">
      <div ref={box} className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-48 items-center gap-3">
          <span className="bg-primary/10 text-primary flex size-9 shrink-0 items-center justify-center rounded-lg">
            <AudioLines className="size-4" />
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-medium" title={title}>{title}</span>
            <span className="text-muted-foreground text-xs">{item.source}</span>
          </span>
        </div>
        <div className="min-w-0 flex-[2_1_16rem]">
          {failedNonce === item.nonce ? <p className="text-muted-foreground text-sm">This audio can't be played.</p> : <AudioResult key={item.nonce} src={item.src} autoPlay />}
        </div>
        <Button variant="ghost" size="icon" className="shrink-0" aria-label="Close Now playing bar" onClick={closeBar}>
          <X />
        </Button>
      </div>
    </div>
  );
}
