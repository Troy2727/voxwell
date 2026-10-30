import { useEffect, useMemo, useState } from 'react';
import { Check, Copy, Download, Sparkles } from 'lucide-react';
import { api, sendJson } from '../../api';
import { ChoiceSelect } from '@/components/choice-select';
import { ErrorAlert, Field, message, Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface Preset {
  id: string;
  label: string;
  instruction: string;
}

interface Edited {
  text: string;
  chunks: number;
  kept: number;
}

const CUSTOM = 'custom';
const MAX_DIFF_WORDS = 2500; // the diff compares every word pair, so longer texts are shown unmarked

interface Piece {
  word: string;
  changed: boolean;
}

/** The words of `a` and `b`, with those outside their longest common subsequence marked as changed. */
function wordDiff(a: string, b: string): { before: Piece[]; after: Piece[] } {
  const x = a.split(/\s+/).filter(Boolean);
  const y = b.split(/\s+/).filter(Boolean);
  const plain = (w: string[]) => w.map((word) => ({ word, changed: false }));
  const before = plain(x);
  const after = plain(y);
  if (x.length > MAX_DIFF_WORDS || y.length > MAX_DIFF_WORDS) return { before, after };
  const width = y.length + 1;
  const lcs = new Uint16Array((x.length + 1) * width);
  for (let i = x.length - 1; i >= 0; i--)
    for (let j = y.length - 1; j >= 0; j--)
      lcs[i * width + j] = x[i] === y[j] ? lcs[(i + 1) * width + j + 1] + 1 : Math.max(lcs[(i + 1) * width + j], lcs[i * width + j + 1]);
  let i = 0;
  let j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) {
      i++;
      j++;
    } else if (lcs[(i + 1) * width + j] >= lcs[i * width + j + 1]) before[i++].changed = true;
    else after[j++].changed = true;
  }
  while (i < x.length) before[i++].changed = true;
  while (j < y.length) after[j++].changed = true;
  return { before, after };
}

function Words({ pieces, mark }: { pieces: Piece[]; mark: string }) {
  return (
    <p className="max-h-[320px] overflow-auto text-sm leading-relaxed whitespace-pre-wrap">
      {pieces.map((p, i) => (
        <span key={i} className={p.changed ? mark : undefined}>
          {p.word}{' '}
        </span>
      ))}
    </p>
  );
}

/** Edit a transcript with the local AI model: pick an instruction, compare, then accept, copy or download. */
export function EditPanel({ jobId, title, text }: { jobId: string; title: string; text: string }) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [choice, setChoice] = useState('filler');
  const [custom, setCustom] = useState('');
  const [base, setBase] = useState(text); // the text the next edit starts from: the original, or an accepted edit
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<Edited | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api<Preset[]>('/api/transcription/edit/presets').then(setPresets, (e) => setError(message(e)));
  }, []);

  const diff = useMemo(() => (result ? wordDiff(base, result.text) : null), [base, result]);
  const options: [string, string][] = [...presets.map((p): [string, string] => [p.id, p.label]), [CUSTOM, 'Write my own…']];
  const ready = choice !== CUSTOM || custom.trim() !== '';

  async function run() {
    setBusy(true);
    setError('');
    setResult(null);
    setCopied(false);
    const wording = choice === CUSTOM ? { instruction: custom } : { preset: choice };
    try {
      // The first edit names the saved transcript; once an edit is accepted, its text is sent instead.
      const source = base === text ? { job_id: jobId } : { text: base };
      setResult(await sendJson<Edited>('/api/transcription/edit', 'POST', { ...source, ...wording }));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  const copy = (value: string) => navigator.clipboard.writeText(value).then(() => setCopied(true));
  function download(value: string) {
    const url = URL.createObjectURL(new Blob([value + '\n'], { type: 'text/plain;charset=utf-8' }));
    const link = Object.assign(document.createElement('a'), { href: url, download: `${title} (edited).txt` });
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Section title="Clean up with AI" description="A local AI model edits the text. Review the changes before you use them.">
      <div className="flex flex-wrap items-end gap-4">
        <Field label="Instruction" className="w-full sm:w-64">
          <ChoiceSelect options={options} value={choice} onChange={setChoice} disabled={busy} />
        </Field>
        {choice === CUSTOM && (
          <Field label="Your instruction" className="w-full sm:flex-1">
            <Input value={custom} maxLength={500} placeholder="e.g. split into short paragraphs" onChange={(e) => setCustom(e.target.value)} />
          </Field>
        )}
        <Button disabled={busy || !ready || presets.length === 0} onClick={run}>
          <Sparkles /> {busy ? 'Editing…' : 'Edit'}
        </Button>
      </div>
      {busy && <p className="text-muted-foreground text-sm">The first edit downloads the model, and long transcripts take a while.</p>}
      <ErrorAlert message={error} />

      {result && diff && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">Original</h3>
              <Words pieces={diff.before} mark="bg-destructive/20 rounded-sm" />
            </div>
            <div className="flex flex-col gap-1.5">
              <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">Edited</h3>
              <Words pieces={diff.after} mark="bg-primary/20 rounded-sm" />
            </div>
          </div>
          {result.kept > 0 && (
            <p className="text-muted-foreground text-sm">
              {result.kept} of {result.chunks} parts could not be edited and were left as they were.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={() => {
                setBase(result.text);
                setResult(null);
              }}
            >
              <Check /> Accept
            </Button>
            <Button size="sm" variant="outline" onClick={() => copy(result.text)}>
              <Copy /> {copied ? 'Copied' : 'Copy'}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => download(result.text)}>
              <Download /> Download TXT
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setResult(null)}>
              Discard
            </Button>
          </div>
        </>
      )}
      {base !== text && !result && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground flex-1">Showing your accepted edit. Edit again to build on it.</span>
          <Button size="sm" variant="outline" onClick={() => copy(base)}>
            <Copy /> {copied ? 'Copied' : 'Copy accepted text'}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => download(base)}>
            <Download /> Download TXT
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setBase(text)}>
            Start over from the original
          </Button>
        </div>
      )}
    </Section>
  );
}
