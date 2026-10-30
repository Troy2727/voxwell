import { useCallback, useEffect, useState } from 'react';
import { Pencil, Plus, Save, Trash2, Volume2 } from 'lucide-react';
import { toast } from 'sonner';
import { api, apiUrl, listVoices, sendJson, Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { ConfirmButton } from '@/components/confirm-button';
import { ErrorAlert, Field, message, Page as PageLayout, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { LANGUAGES } from '../voice_cloning/languages';

interface Entry {
  id: string;
  word: string;
  respelling: string;
  case_sensitive: boolean;
  whole_word: boolean;
}

export default function Page() {
  const [language, setLanguage] = useState('en');
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [word, setWord] = useState('');
  const [respelling, setRespelling] = useState('');
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [wholeWord, setWholeWord] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [voiceId, setVoiceId] = useState('');
  const [sample, setSample] = useState('');
  const [rewritten, setRewritten] = useState('');
  const [hearing, setHearing] = useState(false);
  const [hearError, setHearError] = useState('');
  const [audioUrl, setAudioUrl] = useState('');

  const refresh = useCallback(
    () =>
      api<Entry[]>(`/api/pronunciation/entries?language=${language}`).then(setEntries, (e: Error) => {
        setEntries([]);
        setError(e.message);
      }),
    [language],
  );
  useEffect(() => {
    setEntries(null);
    setRewritten('');
    setAudioUrl('');
    void refresh();
  }, [refresh]);
  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
  }, []);

  function reset() {
    setEditing(null);
    setWord('');
    setRespelling('');
    setCaseSensitive(false);
    setWholeWord(true);
  }

  function edit(e: Entry) {
    setEditing(e.id);
    setWord(e.word);
    setRespelling(e.respelling);
    setCaseSensitive(e.case_sensitive);
    setWholeWord(e.whole_word);
  }

  async function save() {
    setSaving(true);
    setError('');
    const body = { language, word, respelling, case_sensitive: caseSensitive, whole_word: wholeWord };
    try {
      if (editing) await sendJson(`/api/pronunciation/entries/${editing}`, 'PUT', body);
      else await sendJson('/api/pronunciation/entries', 'POST', body);
      toast.success(`Saved "${word.trim()}"`);
      reset();
      await refresh();
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove(e: Entry) {
    setError('');
    try {
      await api(`/api/pronunciation/entries/${e.id}?language=${language}`, { method: 'DELETE' });
      if (editing === e.id) reset();
      await refresh();
    } catch (err) {
      setError(message(err));
    }
  }

  async function hear() {
    setHearing(true);
    setHearError('');
    setAudioUrl('');
    try {
      const preview = await sendJson<{ text: string }>('/api/pronunciation/preview', 'POST', { text: sample, language });
      setRewritten(preview.text);
      // Speech applies the dictionary itself, so the original text goes in.
      const res = await sendJson<{ url: string }>('/api/voice_cloning/synthesize', 'POST', {
        text: sample,
        language,
        voice_id: voiceId || null,
      });
      setAudioUrl(apiUrl(res.url));
    } catch (e) {
      setHearError(message(e));
    } finally {
      setHearing(false);
    }
  }

  return (
    <PageLayout title="Pronunciation" description="Teach every voice how to say names, brands and jargon. Applies to all speech Voxwell makes.">
      <Section title="Language" description="Each language has its own list.">
        <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} />
      </Section>

      <Section title={editing ? 'Edit word' : 'Add a word'} description="Write the respelling the way it should sound, e.g. Nguyen becomes win.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Word" htmlFor="pron-word">
            <Input id="pron-word" value={word} maxLength={100} onChange={(e) => setWord(e.target.value)} placeholder="Nguyen" />
          </Field>
          <Field label="Respelling" htmlFor="pron-respelling">
            <Input id="pron-respelling" value={respelling} maxLength={200} onChange={(e) => setRespelling(e.target.value)} placeholder="win" />
          </Field>
        </div>
        <div className="flex flex-wrap gap-6">
          <Label className="gap-2 font-normal">
            <Checkbox checked={caseSensitive} onCheckedChange={(v) => setCaseSensitive(v === true)} />
            Match capitalization
          </Label>
          <Label className="gap-2 font-normal">
            <Checkbox checked={wholeWord} onCheckedChange={(v) => setWholeWord(v === true)} />
            Whole word only
          </Label>
        </div>
        <div className="flex gap-2">
          <Button disabled={saving || !word.trim() || !respelling.trim()} onClick={save}>
            {editing ? <Save /> : <Plus />} {saving ? 'Saving…' : editing ? 'Save changes' : 'Add word'}
          </Button>
          {editing && (
            <Button variant="outline" onClick={reset}>
              Cancel
            </Button>
          )}
        </div>
        <ErrorAlert message={error} />
      </Section>

      <Section title="Your words">
        {entries === null ? (
          <Skeleton className="h-16 w-full" />
        ) : entries.length === 0 ? (
          <p className="text-muted-foreground text-sm">No words for this language yet.</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {entries.map((e) => (
              <li key={e.id} className="flex items-center gap-3 py-2">
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm font-medium">
                    {e.word} <span className="text-muted-foreground font-normal">→ {e.respelling}</span>
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {e.whole_word ? 'Whole word' : 'Anywhere in a word'} · {e.case_sensitive ? 'Case-sensitive' : 'Any capitalization'}
                  </span>
                </div>
                <Button variant="outline" size="sm" onClick={() => edit(e)}>
                  <Pencil /> Edit
                </Button>
                <ConfirmButton title={`Delete "${e.word}"?`} onConfirm={() => remove(e)}>
                  <Trash2 /> Delete
                </ConfirmButton>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Hear it" description="Say a sentence with your words applied.">
        <Field label="Voice">
          <VoiceSelect voices={voices} value={voiceId} onChange={setVoiceId} disabled={voices === null} />
        </Field>
        <Field label="Sentence" htmlFor="pron-sample">
          <Textarea id="pron-sample" rows={3} maxLength={2000} value={sample} onChange={(e) => setSample(e.target.value)} placeholder="Ask Ms. Nguyen about it." />
        </Field>
        <div>
          <Button disabled={hearing || !sample.trim()} onClick={hear}>
            <Volume2 /> {hearing ? 'Generating…' : 'Hear it'}
          </Button>
        </div>
        <ErrorAlert message={hearError} />
        {rewritten && (
          <p className="text-muted-foreground text-sm">
            The voice reads: <span className="text-foreground">{rewritten}</span>
          </p>
        )}
        {audioUrl && <AudioResult src={audioUrl} download="voxwell-pronunciation.wav" />}
      </Section>
    </PageLayout>
  );
}
