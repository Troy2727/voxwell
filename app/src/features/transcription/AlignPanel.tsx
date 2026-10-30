import { useState } from 'react';
import { AlignLeft, Download } from 'lucide-react';
import { api } from '../../api';
import { ChoiceSelect } from '@/components/choice-select';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, Field, message, Section } from '@/components/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

interface Cue {
  start: number;
  end: number;
  text: string;
}

interface Aligned {
  cues: Cue[];
  srt: string;
  vtt: string;
  matched: number;
  total: number;
  fallback: boolean;
}

const AUTO = 'auto';
const LANGUAGES: [string, string][] = [
  [AUTO, 'Auto-detect'], ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'],
  ['it', 'Italian'], ['pt', 'Portuguese'], ['nl', 'Dutch'], ['ru', 'Russian'], ['zh', 'Chinese'],
  ['ja', 'Japanese'], ['ko', 'Korean'], ['ar', 'Arabic'], ['hi', 'Hindi'], ['tr', 'Turkish'],
];

const stamp = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;

/** Time a script you already have against its recording, then preview and download the subtitles. */
export function AlignPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [script, setScript] = useState('');
  const [language, setLanguage] = useState(AUTO);
  const [maxChars, setMaxChars] = useState('42');
  const [maxSeconds, setMaxSeconds] = useState('6');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Aligned | null>(null);

  async function run() {
    if (!file) return;
    setBusy(true);
    setError('');
    setResult(null);
    const form = new FormData();
    form.append('file', file);
    form.append('script', script);
    form.append('language', language === AUTO ? '' : language);
    form.append('max_chars', maxChars);
    form.append('max_seconds', maxSeconds);
    try {
      setResult(await api<Aligned>('/api/transcription/align', { method: 'POST', body: form }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  function download(fmt: 'srt' | 'vtt') {
    const type = fmt === 'srt' ? 'application/x-subrip' : 'text/vtt';
    const url = URL.createObjectURL(new Blob([result![fmt]], { type: `${type};charset=utf-8` }));
    const name = file ? file.name.replace(/\.[^.]*$/, '') : 'subtitles';
    Object.assign(document.createElement('a'), { href: url, download: `${name}.${fmt}` }).click();
    URL.revokeObjectURL(url);
  }

  return (
    <Section
      title="Subtitles from a script"
      description="Already have the words? Add the recording and paste the script: every word is timed against the audio."
    >
      <FileDrop file={file} onFile={setFile} accept="audio/*,video/*,.mkv" disabled={busy} />
      <Field label="Script" hint="Plain text, exactly as spoken or close to it. Punctuation and capitals are kept in the subtitles.">
        <Textarea value={script} onChange={(e) => setScript(e.target.value)} rows={6} disabled={busy} placeholder="Paste the script here…" />
      </Field>
      <div className="flex flex-wrap items-end gap-4">
        <Field label="Language" className="w-full sm:w-48">
          <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} disabled={busy} />
        </Field>
        <Field label="Characters per subtitle" className="w-full sm:w-44">
          <Input type="number" min={10} max={200} value={maxChars} onChange={(e) => setMaxChars(e.target.value)} disabled={busy} />
        </Field>
        <Field label="Seconds per subtitle" className="w-full sm:w-44">
          <Input type="number" min={1} max={30} value={maxSeconds} onChange={(e) => setMaxSeconds(e.target.value)} disabled={busy} />
        </Field>
        <Button disabled={!file || !script.trim() || busy} onClick={run}>
          <AlignLeft /> {busy ? 'Aligning…' : 'Align'}
        </Button>
      </div>
      {busy && <p className="text-muted-foreground text-sm">Listening to the recording; long files take a while.</p>}
      <ErrorAlert message={error} />

      {result && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={result.fallback ? 'destructive' : 'secondary'}>
              {result.matched} of {result.total} words matched
            </Badge>
            {result.fallback && (
              <span className="text-muted-foreground text-sm">
                Nothing matched the audio, so the times are estimates. Check the script and the language.
              </span>
            )}
          </div>
          <div className="flex max-h-[360px] flex-col gap-1.5 overflow-auto">
            {result.cues.map((c, i) => (
              <div key={i} className="flex items-baseline gap-3 text-sm">
                <span className="text-muted-foreground w-24 shrink-0 text-xs tabular-nums">
                  {stamp(c.start)} – {stamp(c.end)}
                </span>
                <span>{c.text}</span>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {(['srt', 'vtt'] as const).map((fmt) => (
              <Button key={fmt} variant="secondary" size="sm" onClick={() => download(fmt)}>
                <Download /> Download {fmt.toUpperCase()}
              </Button>
            ))}
          </div>
        </>
      )}
    </Section>
  );
}
