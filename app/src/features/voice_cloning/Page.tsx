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
import { usePromptMenu, type PromptItem } from '@/components/prompt-menu';
import { VoiceSelect } from '@/components/voice-select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { usePersisted } from '@/lib/persisted';
import { CuePicker, Cues } from './CuePicker';
import { FreeTheGpu } from './FreeTheGpu';
import { LANGUAGES } from './languages';
import { addTake, MAX_WAITING, onFinished, useTakes, waitingCount } from './queue';
import { TakeQueue } from './TakeQueue';

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
  const takes = useTakes();
  const inQueue = takes.some((t) => t.status === 'running' || t.status === 'waiting');
  const waiting = takes.filter((t) => t.status === 'waiting').length;
  const [error, setError] = useState('');
  const [audioUrl, setAudioUrl] = useState('');
  const [cues, setCues] = useState<Cues | null>(null);
  const [cueNote, setCueNote] = useState('');
  const textBox = useRef<HTMLTextAreaElement>(null);
  const cuesHere = !!cues && cues.languages.includes(language);
  const cuesOffered = cuesHere && cues.available;
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

  // The newest take that finishes while the page is open becomes the result below.
  useEffect(
    () =>
      onFinished((take) => {
        setAudioUrl(apiUrl(take.url!));
        setCueNote(!take.cuesIgnored
          ? ''
          : cues?.languages.includes(take.language)
            ? 'The cues were left out this time: they need a voice clip longer than five seconds and the cue model, which could not be used. See the Voxwell log.'
            : 'Cues work in English only, so they were left out.');
      }),
    [cues],
  );

  // A remembered voice may have been deleted since.
  useEffect(() => {
    if (voices && voiceId && !voices.some((v) => v.id === voiceId)) setVoiceId('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voices]);

  /** `tag` ("[pause 1]", "[laugh]") put into `source` between `start` and `end`, spaced from its neighbors. */
  function withTag(source: string, tag: string, start: number, end: number) {
    const before = source.slice(0, start);
    tag = `${before && !before.endsWith(' ') ? ' ' : ''}${tag} `;
    return { text: before + tag + source.slice(end).trimStart(), cursor: start + tag.length };
  }

  /** A / menu entry that puts `tag` where the typed word was. */
  const tagItem = (label: string, hint: string, tag: string): PromptItem => ({ label, hint, pick: (t, at) => withTag(t, tag, at, at) });

  /** Put `tag` at the cursor, in place of any selection. */
  function insertTag(tag: string) {
    const start = textBox.current?.selectionStart ?? text.length;
    const end = textBox.current?.selectionEnd ?? text.length;
    const next = withTag(text, tag, start, end);
    setText(next.text);
    // After React has put the new text in the box, so the cursor isn't reset by it.
    requestAnimationFrame(() => {
      textBox.current?.focus();
      textBox.current?.setSelectionRange(next.cursor, next.cursor);
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

  const prompt = usePromptMenu({
    box: textBox,
    text,
    setText,
    onSubmit: () => {
      if (text.trim()) add();
    },
    sources: {
      '@': { title: 'Voices', items: (voices ?? []).map((v) => ({ label: v.name, hint: 'voice', pick: () => setVoiceId(v.id) })) },
      '/': {
        title: cuesOffered ? 'Pauses and cues' : 'Pauses',
        items: [
          ...PAUSES.map(([label, seconds]) => tagItem(`pause-${label.toLowerCase()}`, `${seconds} s`, `[pause ${seconds}]`)),
          // Typed words can't hold spaces, so "clear throat" is found as "clear-throat".
          ...(cuesOffered ? cues.groups.flatMap((g) => g.tags.map(({ tag }) => tagItem(tag.replaceAll(' ', '-'), g.label, `[${tag}]`))) : []),
        ],
      },
    },
  });

  /** Generate, or add to the queue while another take renders: a snapshot of what is on screen now. */
  function add() {
    const voiceName = voices?.find((v) => v.id === voiceId)?.name ?? 'Default voice';
    const queued = inQueue;
    if (!addTake({ text, language, voiceId: voiceId || null, voiceName, effects: isNeutral(fx) ? null : fx })) {
      toast.warning(`The queue is full (${MAX_WAITING} takes). Wait for some to finish first.`);
      return;
    }
    if (queued) toast.info(`Queued. ${waitingCount()} waiting.`);
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
          hint={`${text.length} / 2000. Type [pause 2] anywhere for two seconds of silence, up to 10. @ picks a voice, / adds a pause${cuesOffered ? ' or a cue' : ''}, Ctrl+Enter generates.${cueHint}`}
        >
          <div className="relative">
            <Textarea ref={textBox} id="clone-text" rows={5} maxLength={2000} value={text} placeholder="Type what the voice should say…" {...prompt.inputProps} />
            {prompt.menu}
          </div>
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          {PAUSES.map(([label, seconds]) => (
            <Button key={label} variant="outline" size="sm" aria-label={`${label} pause`} onClick={() => insertTag(`[pause ${seconds}]`)}>
              <Pause /> {label}
            </Button>
          ))}
          {cuesHere && <CuePicker groups={cues.groups} disabled={!cues.available} onPick={insertTag} />}
        </div>
        <EffectsControls value={fx} onChange={setFx} resettable />
        <div>
          <Button disabled={!text.trim()} onClick={add}>
            <Volume2 /> {inQueue ? 'Queue this take' : 'Generate'}
            {waiting > 0 && <Badge variant="secondary" aria-label={`${waiting} waiting`}>{waiting}</Badge>}
          </Button>
        </div>
        <ErrorAlert message={error} />
        {cueNote && <p className="text-sm text-muted-foreground">{cueNote}</p>}
        {audioUrl && <AudioResult src={audioUrl} download="voxwell-speech.wav" />}
      </Section>

      <TakeQueue takes={takes} />

      <FreeTheGpu />
    </PageLayout>
  );
}
