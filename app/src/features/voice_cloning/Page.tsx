import { useEffect, useRef, useState } from 'react';
import { Pause, Upload, Volume2 } from 'lucide-react';
import { toast } from 'sonner';
import { api, apiUrl, listVoices, Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { EffectsControls, isNeutral, NO_EFFECTS, reviveEffects } from '@/components/effects-controls';
import { ApprovalCard } from '@/components/approval-card';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, Field, message, Page as PageLayout, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { usePersisted } from '@/lib/persisted';
import { CuePicker, Cues } from './CuePicker';
import { LANGUAGES } from './languages';

const PAUSES: [string, number][] = [['Short', 0.5], ['Medium', 1], ['Long', 2]];

const CONSENT_MINE = "It's my own voice";
const CONSENT_AGREED = 'Someone who agreed to be cloned';
const CONSENT_NO = "Someone who hasn't agreed";

export default function Page() {
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [voiceId, setVoiceId] = usePersisted('voxwell.voice_cloning.voice', '');
  const [name, setName] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [askingConsent, setAskingConsent] = useState(false);
  const [refused, setRefused] = useState(false);
  const [text, setText] = useState('');
  const [language, setLanguage] = usePersisted('voxwell.voice_cloning.language', 'en');
  const [fx, setFx] = usePersisted('voxwell.voice_cloning.effects', NO_EFFECTS, reviveEffects);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [audioUrl, setAudioUrl] = useState('');
  const [cues, setCues] = useState<Cues | null>(null);
  const [cueNote, setCueNote] = useState('');
  const textBox = useRef<HTMLTextAreaElement>(null);
  const cuesHere = !!cues && cues.languages.includes(language);
  const cueHint = !cuesHere
    ? ''
    : cues.available
      ? ' Cues such as [laugh] ask the voice for that sound or manner.'
      : ' Cues are unavailable: their model (Chatterbox-Turbo) is missing or failed to load; see the Voxwell log.';

  const refresh = () =>
    listVoices().then(setVoices, (e: Error) => {
      setVoices([]);
      setError(e.message);
    });
  useEffect(() => {
    void refresh();
    // Without it (an older backend), the page just offers no cues.
    api<{ cues?: Cues }>('/api/voice_cloning/status').then((s) => setCues(s.cues ?? null), () => setCues(null));
  }, []);

  // A remembered voice may have been deleted since.
  useEffect(() => {
    if (voices && voiceId && !voices.some((v) => v.id === voiceId)) setVoiceId('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voices]);

  /** Put `tag` ("[pause 1]", "[laugh]") at the cursor, in place of any selection, spaced from its neighbors. */
  function insertTag(tag: string) {
    const start = textBox.current?.selectionStart ?? text.length;
    const end = textBox.current?.selectionEnd ?? text.length;
    const before = text.slice(0, start);
    tag = `${before && !before.endsWith(' ') ? ' ' : ''}${tag} `;
    setText(before + tag + text.slice(end).trimStart());
    // After React has put the new text in the box, so the cursor isn't reset by it.
    requestAnimationFrame(() => {
      textBox.current?.focus();
      textBox.current?.setSelectionRange(start + tag.length, start + tag.length);
    });
  }

  async function upload() {
    if (!file || !name.trim()) return;
    setUploading(true);
    setError('');
    try {
      const body = new FormData();
      body.append('name', name.trim());
      body.append('file', file);
      const voice = await api<Voice>('/api/voice_cloning/voices', { method: 'POST', body });
      await refresh();
      setVoiceId(voice.id);
      setName('');
      setFile(null);
      toast.success(`Saved "${voice.name}"`);
    } catch (e) {
      setError(message(e));
    } finally {
      setUploading(false);
    }
  }

  async function generate() {
    setBusy(true);
    setError('');
    setAudioUrl('');
    setCueNote('');
    try {
      const res = await api<{ id: string; url: string; cues_ignored?: boolean }>('/api/voice_cloning/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, language, voice_id: voiceId || null, effects: isNeutral(fx) ? null : fx }),
      });
      setAudioUrl(apiUrl(res.url));
      if (res.cues_ignored) {
        setCueNote(cuesHere
          ? 'The cues were left out this time: they need a voice clip longer than five seconds and the cue model, which could not be used. See the Voxwell log.'
          : 'Cues work in English only, so they were left out.');
      }
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageLayout title="Voice cloning" description="Clone a voice from a short clip, then make it say anything.">
      <Section title="Add a voice" description="A few seconds of clean speech: WAV, MP3, FLAC or OGG.">
        <Field label="Name" htmlFor="clone-name">
          <Input id="clone-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="My voice" />
        </Field>
        <Field label="Reference clip">
          <FileDrop file={file} onFile={setFile} accept=".wav,.mp3,.flac,.ogg,audio/*" disabled={uploading} />
        </Field>
        {askingConsent ? (
          <ApprovalCard
            title="Before cloning this voice"
            questions={[{ question: 'Whose voice is in this clip?', options: [CONSENT_MINE, CONSENT_AGREED, CONSENT_NO] }]}
            onCancel={() => setAskingConsent(false)}
            onDone={([answer]) => {
              setAskingConsent(false);
              if (answer === CONSENT_NO) setRefused(true);
              else void upload();
            }}
          />
        ) : (
          <div>
            <Button
              disabled={uploading || !file || !name.trim()}
              onClick={() => {
                setRefused(false);
                setAskingConsent(true);
              }}
            >
              <Upload /> {uploading ? 'Uploading…' : 'Upload voice'}
            </Button>
          </div>
        )}
        {refused && (
          <p role="alert" className="text-sm">
            Voxwell only clones a voice with the speaker's permission, so this clip was not uploaded. Ask them first, or make a new voice
            in Voice design.
          </p>
        )}
      </Section>

      <Section title="Generate speech">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Voice" hint={voices !== null && voices.length === 0 ? 'No saved voices yet. Upload one above.' : undefined}>
            <VoiceSelect voices={voices} value={voiceId} onChange={setVoiceId} disabled={voices === null} />
          </Field>
          <Field label="Language" htmlFor="clone-language">
            <ChoiceSelect id="clone-language" options={LANGUAGES} value={language} onChange={setLanguage} />
          </Field>
        </div>
        <Field
          label="Text"
          htmlFor="clone-text"
          hint={`${text.length} / 2000. Type [pause 2] anywhere for two seconds of silence, up to 10.${cueHint}`}
        >
          <Textarea ref={textBox} id="clone-text" rows={5} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} placeholder="Type what the voice should say…" />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          {PAUSES.map(([label, seconds]) => (
            <Button key={label} variant="outline" size="sm" aria-label={`${label} pause`} disabled={busy} onClick={() => insertTag(`[pause ${seconds}]`)}>
              <Pause /> {label}
            </Button>
          ))}
          {cuesHere && <CuePicker groups={cues.groups} disabled={busy || !cues.available} onPick={insertTag} />}
        </div>
        <EffectsControls value={fx} onChange={setFx} disabled={busy} resettable />
        <div>
          <Button disabled={busy || !text.trim()} onClick={generate}>
            <Volume2 /> {busy ? 'Generating…' : 'Generate'}
          </Button>
        </div>
        <ErrorAlert message={error} />
        {cueNote && <p className="text-sm text-muted-foreground">{cueNote}</p>}
        {audioUrl && <AudioResult src={audioUrl} download="voxwell-speech.wav" />}
      </Section>
    </PageLayout>
  );
}
