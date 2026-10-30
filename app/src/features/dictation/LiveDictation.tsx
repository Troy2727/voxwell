import { type ReactNode, useEffect, useState } from 'react';
import { Copy, Radio, Square, Trash2 } from 'lucide-react';
import { ErrorAlert, Field, Muted, Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { LiveWaveform } from '@/components/ui/live-waveform';
import { Slider } from '@/components/ui/slider';
import { type LiveMessage, useLiveAudio } from '@/hooks/use-live-audio';

/** Live mode of the Dictation page: speech is transcribed turn by turn, each turn as it ends. */
export default function LiveDictation({ tabs, fields, device, language, muted, onActiveChange }: {
  tabs: ReactNode;
  fields: ReactNode;
  device: string;
  language: string;
  muted: boolean;
  onActiveChange: (active: boolean) => void;
}) {
  const [silence, setSilence] = useState(0.8);
  const [turns, setTurns] = useState<string[]>([]);
  const [pending, setPending] = useState(0);
  const [warning, setWarning] = useState('');
  const [turnError, setTurnError] = useState('');
  const [copied, setCopied] = useState(false);

  const onMessage = (m: LiveMessage) => {
    if (m.type === 'turn_end' && m.index != null) setPending((p) => p + 1);
    else if (m.type === 'turn') {
      setPending((p) => Math.max(0, p - 1));
      const text = typeof m.text === 'string' ? m.text.trim() : '';
      if (text) setTurns((t) => [...t, text]);
    } else if (m.type === 'error' && m.index != null) {
      setPending((p) => Math.max(0, p - 1));
      setTurnError(m.message ?? 'A turn could not be transcribed.');
    } else if (m.type === 'warning') setWarning(m.message ?? '');
  };
  const live = useLiveAudio('/api/dictation/live', onMessage);
  const active = live.status !== 'idle';
  useEffect(() => onActiveChange(active), [active, onActiveChange]);
  useEffect(() => {
    if (!active) setPending(0);
  }, [active]);

  const begin = () => {
    setWarning('');
    setTurnError('');
    setCopied(false);
    void live.start({ silence_ms: Math.round(silence * 1000), language: language === 'auto' ? null : language }, device || undefined);
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(turns.join(' '));
      setCopied(true);
    } catch {
      setTurnError('Could not copy to the clipboard.');
    }
  };

  const state =
    live.status === 'connecting' ? 'Connecting…'
      : live.status === 'finishing' ? 'Finishing the last turn…'
        : live.status !== 'listening' ? ''
          : live.speaking ? '● Speaking…'
            : pending ? 'Turn finished, transcribing…'
              : 'Listening…';

  return (
    <>
      <Section title="Record" action={tabs}>
        <div className="bg-muted/30 flex flex-col items-center gap-4 rounded-xl border p-6">
          <LiveWaveform active={live.status === 'listening'} processing={live.status === 'finishing'} deviceId={device || undefined} height={64} mode="static" className="w-full" />
          <div className="flex items-center gap-3">
            <Button
              size="lg"
              variant={active ? 'destructive' : 'default'}
              className="rounded-full px-6"
              disabled={live.status === 'finishing' || (!active && muted)}
              onClick={active ? live.stop : begin}
            >
              {active ? <Square /> : <Radio />} {active ? 'Stop' : 'Start live'}
            </Button>
            {state && (
              <span aria-live="polite" className={live.speaking ? 'text-destructive text-sm' : 'text-muted-foreground text-sm'}>
                {state}
              </span>
            )}
          </div>
        </div>
        {fields}
        <Field label={`Pause that ends a turn: ${silence.toFixed(1)} s`} hint="Shorter answers faster; longer lets you pause mid-sentence.">
          <Slider min={0.3} max={2} step={0.1} value={[silence]} onValueChange={([v]) => setSilence(v)} disabled={active} aria-label="Pause that ends a turn" className="py-2" />
        </Field>
        {warning && <Muted className="text-xs">{warning}</Muted>}
        <div role="alert">
          <ErrorAlert message={live.error || turnError} />
        </div>
      </Section>

      <Section
        title="Live transcript"
        action={
          turns.length > 0 && (
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={copy}>
                <Copy /> {copied ? 'Copied' : 'Copy'}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setTurns([])} disabled={active}>
                <Trash2 /> Clear
              </Button>
            </div>
          )
        }
      >
        {turns.length === 0 ? (
          <Muted>Nothing yet. Press Start live and speak; each turn appears when you pause.</Muted>
        ) : (
          <div className="divide-y">
            {turns.map((t, i) => (
              <p className="py-2 leading-relaxed" key={i}>
                {t}
              </p>
            ))}
          </div>
        )}
      </Section>
    </>
  );
}
