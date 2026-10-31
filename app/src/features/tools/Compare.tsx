import { useState } from 'react';
import { Headphones, Plus, Trash2 } from 'lucide-react';
import { apiUrl, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { ErrorAlert, Field, message, Muted } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { LANGUAGES } from '../voice_cloning/languages';

const MAX_COMPARE = 4;

export function Compare({ voices }: { voices: Voice[] }) {
  const [text, setText] = useState('The quick brown fox jumps over the lazy dog.');
  const [language, setLanguage] = useState('en');
  const [chosen, setChosen] = useState<string[]>(['', '']);
  const [results, setResults] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState('');

  async function run() {
    setError('');
    setResults({});
    // One voice at a time, so each result appears as soon as it is ready.
    for (const [i, voice_id] of chosen.entries()) {
      setBusy(i);
      try {
        const res = await sendJson<{ url: string }>('/api/tools/speak', 'POST', { text, language, voice_id: voice_id || null });
        setResults((r) => ({ ...r, [i]: res.url }));
      } catch (e) {
        setError(message(e));
        break;
      }
    }
    setBusy(null);
  }

  const name = (id: string) => voices.find((v) => v.id === id)?.name ?? 'Default voice';

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
        <Field label="Text" htmlFor="compare-text">
          <Textarea id="compare-text" rows={2} maxLength={300} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <Field label="Language">
          <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} />
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {chosen.map((voice, i) => (
          <div key={i} className="flex flex-col gap-2 rounded-lg border p-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Voice {i + 1}</span>
              {busy === i && <Muted className="text-xs">Speaking…</Muted>}
              {chosen.length > 2 && (
                <Button variant="ghost" size="icon" className="ml-auto size-7" aria-label="Remove" disabled={busy !== null} onClick={() => setChosen(chosen.filter((_, j) => j !== i))}>
                  <Trash2 />
                </Button>
              )}
            </div>
            <VoiceSelect voices={voices} value={voice} onChange={(v) => setChosen(chosen.map((c, j) => (j === i ? v : c)))} />
            {results[i] && (
              <div aria-label={name(voice)}>
                <AudioResult src={apiUrl(results[i])} />
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {chosen.length < MAX_COMPARE && (
          <Button variant="outline" disabled={busy !== null} onClick={() => setChosen([...chosen, ''])}>
            <Plus /> Add a voice
          </Button>
        )}
        <Button disabled={busy !== null || !text.trim()} onClick={run}>
          <Headphones /> {busy !== null ? 'Comparing…' : 'Compare'}
        </Button>
      </div>
      <ErrorAlert message={error} />
    </>
  );
}
