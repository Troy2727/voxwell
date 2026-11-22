import { useEffect, useRef, useState } from 'react';
import { Captions, Merge, Play, Undo2 } from 'lucide-react';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { EffectsControls, isNeutral, NO_EFFECTS, reviveEffects } from '@/components/effects-controls';
import { FileDrop } from '@/components/file-drop';
import { JobProgress } from '@/components/job-progress';
import { NaturalPauses } from '@/components/natural-pauses';
import { ErrorAlert, Field, message, Muted, Page as PageLayout, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { usePersisted } from '@/lib/persisted';
import { LANGUAGES } from '../voice_cloning/languages';

interface Story {
  id: string;
  title: string;
  state: 'queued' | 'running' | 'done' | 'error';
  step: string;
  percent: number;
  error: string | null;
  audio_url: string;
}

const EXAMPLE = `Anna: Did you hear that?
Tom: Just the wind, love.
The door creaked open, slowly.
Anna: That was not the wind.`;

const DEFAULT_VOICE = 'default';

/** " Start a line with [mood calm], … or [mood intense] to change how it is delivered." ('' without moods) */
function moodHint(moods: string[]) {
  const markers = moods.filter((m) => m !== 'neutral').map((m) => `[mood ${m}]`);
  if (markers.length < 2) return '';
  return ` Start a line with ${markers.slice(0, -1).join(', ')} or ${markers.at(-1)} to change how it is delivered.`;
}

interface JoinResult {
  script: string;
  joined: number;
  too_long: number;
  line: number;
}

/** What a Join lines click did, in words. */
function joinNote({ joined, too_long: tooLong }: JoinResult) {
  if (!joined) return tooLong ? 'Those lines are too long to join (250 characters max).' : 'Nothing to join. Lines need the same speaker and no blank line between them.';
  const done = `Joined ${joined} ${joined === 1 ? 'line' : 'lines'}.`;
  return tooLong ? `${done} ${tooLong} ${tooLong === 1 ? 'pair was' : 'pairs were'} too long to join (250 characters max).` : done;
}

export default function Page() {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [title, setTitle] = useState('');
  const [language, setLanguage] = usePersisted('voxwell.stories.language', 'en');
  const [script, setScript] = useState('');
  const [speakers, setSpeakers] = useState<string[]>([]);
  const [lineCount, setLineCount] = useState(0);
  const [scriptError, setScriptError] = useState('');
  const [cast, setCast] = useState<Record<string, string>>({});
  const [story, setStory] = useState<Story | null>(null);
  const [fx, setFx] = usePersisted('voxwell.stories.effects', NO_EFFECTS, reviveEffects);
  const [naturalPauses, setNaturalPauses] = usePersisted('voxwell.stories.natural_pauses', false, (saved) => saved === true);
  const [error, setError] = useState('');
  const [subtitles, setSubtitles] = useState<File | null>(null);
  const [subtitleVoice, setSubtitleVoice] = useState('');
  const [moods, setMoods] = useState<string[]>([]);
  const timer = useRef<number | undefined>(undefined);
  const parseTimer = useRef<number | undefined>(undefined);
  const scriptBox = useRef<HTMLTextAreaElement>(null);
  const [joining, setJoining] = useState(false);
  const [joinStatus, setJoinStatus] = useState('');
  const [beforeJoin, setBeforeJoin] = useState<string | null>(null);

  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
    // Line moods: the names come from the backend, which owns the script format. No hint if it fails.
    api<{ moods?: string[] }>('/api/stories/status').then((s) => setMoods(s.moods ?? []), () => setMoods([]));
    return () => {
      window.clearTimeout(timer.current);
      window.clearTimeout(parseTimer.current);
    };
  }, []);

  // Ask the backend who speaks, a moment after typing stops; it owns the script format.
  useEffect(() => {
    window.clearTimeout(parseTimer.current);
    if (!script.trim()) {
      setSpeakers([]);
      setScriptError('');
      return;
    }
    parseTimer.current = window.setTimeout(() => {
      sendJson<{ speakers: string[]; lines: number }>('/api/stories/parse', 'POST', { script }).then(
        (res) => {
          setSpeakers(res.speakers);
          setLineCount(res.lines);
          setScriptError('');
        },
        (e) => setScriptError(message(e)),
      );
    }, 400);
  }, [script]);

  const poll = (id: string) =>
    api<Story>(`/api/stories/jobs/${id}`).then(
      (s) => {
        setStory(s);
        if (s.state === 'queued' || s.state === 'running') timer.current = window.setTimeout(() => poll(id), 1500);
      },
      (e) => setError(message(e)),
    );

  /** Join lines: the line at the cursor with the next one, or every line the selection touches. */
  async function joinLines() {
    const box = scriptBox.current;
    const start = box?.selectionStart ?? 0;
    // A selection that ends at the start of a line doesn't take that line in.
    const end = Math.max(start, (box?.selectionEnd ?? 0) - (script[(box?.selectionEnd ?? 0) - 1] === '\n' ? 1 : 0));
    const lineAt = (offset: number) => script.slice(0, offset).split('\n').length;
    const total = script.replace(/\n$/, '').split('\n').length; // as the backend counts them
    const first = Math.min(lineAt(start), total);
    const last = Math.min(Math.max(lineAt(end), first + 1), total);
    setJoining(true);
    setError('');
    try {
      const res = await sendJson<JoinResult>('/api/stories/join', 'POST', { script, first_line: first, last_line: last });
      setJoinStatus(joinNote(res));
      if (res.joined) {
        setBeforeJoin(script);
        setScript(res.script);
        const at = res.script.split('\n').slice(0, res.line - 1).join('\n').length + (res.line > 1 ? 1 : 0);
        requestAnimationFrame(() => {
          scriptBox.current?.focus();
          scriptBox.current?.setSelectionRange(at, at);
        });
      }
    } catch (e) {
      setError(message(e));
    } finally {
      setJoining(false);
    }
  }

  async function generate() {
    setError('');
    setStory(null);
    const chosen = Object.fromEntries(speakers.map((s) => [s, cast[s] ?? DEFAULT_VOICE]));
    try {
      const { id } = await sendJson<{ id: string }>('/api/stories/jobs', 'POST', { title, language, script, cast: chosen, effects: isNeutral(fx) ? null : fx, natural_pauses: naturalPauses });
      await poll(id);
    } catch (e) {
      setError(message(e));
    }
  }

  async function generateFromSubtitles() {
    if (!subtitles) return;
    setError('');
    setStory(null);
    const body = new FormData();
    body.append('file', subtitles);
    body.append('language', language);
    body.append('voice_id', subtitleVoice);
    body.append('title', title);
    try {
      const { id } = await api<{ id: string }>('/api/stories/subtitles', { method: 'POST', body });
      await poll(id);
    } catch (e) {
      setError(message(e));
    }
  }

  const working = story?.state === 'queued' || story?.state === 'running';

  return (
    <PageLayout title="Stories" description="Write a script with several speakers and give each one a voice.">
      <Section title="Script">
        <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
          <Field label="Title (optional)" htmlFor="story-title">
            <Input id="story-title" value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Language" htmlFor="story-language">
            <ChoiceSelect id="story-language" options={LANGUAGES} value={language} onChange={setLanguage} />
          </Field>
        </div>
        <Field
          label="Script"
          htmlFor="story-script"
          hint={`One line each, as “Name: what they say”. Lines without a name are read by the Narrator.${moodHint(moods)}`}
        >
          <Textarea
            ref={scriptBox}
            id="story-script"
            rows={10}
            value={script}
            readOnly={joining} // a join's result would overwrite typing meanwhile
            placeholder={EXAMPLE}
            onChange={(e) => {
              setScript(e.target.value);
              setBeforeJoin(null);
              setJoinStatus('');
            }}
            className="font-mono text-sm"
          />
        </Field>
        {!script && (
          <div>
            <Button variant="outline" size="sm" onClick={() => setScript(EXAMPLE)}>Use the example</Button>
          </div>
        )}
        {script && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={joining || !script.trim()}
              title="Merge the line at the cursor, or the selected lines, with the next line when the same person speaks them."
              onClick={() => void joinLines()}
            >
              <Merge /> Join lines
            </Button>
            {beforeJoin !== null && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setScript(beforeJoin);
                  setBeforeJoin(null);
                  setJoinStatus('');
                }}
              >
                <Undo2 /> Undo join
              </Button>
            )}
            <p role="status" className="text-muted-foreground text-xs">{joinStatus}</p>
          </div>
        )}
        <ErrorAlert message={scriptError} />
      </Section>

      {speakers.length > 0 && !scriptError && (
        <Section title="Cast" description={`${lineCount} ${lineCount === 1 ? 'line' : 'lines'}. Give each speaker a voice from Saved voices.`}>
          {speakers.map((speaker) => (
            <div key={speaker} className="grid items-center gap-2 sm:grid-cols-[160px_1fr]">
              <span className="truncate text-sm font-medium">{speaker}</span>
              <VoiceSelect
                voices={voices}
                value={cast[speaker] && cast[speaker] !== DEFAULT_VOICE ? cast[speaker] : ''}
                onChange={(id) => setCast({ ...cast, [speaker]: id || DEFAULT_VOICE })}
              />
            </div>
          ))}
          {voices.length === 0 && <Muted className="text-xs">No saved voices yet; everyone uses the default voice.</Muted>}
          <NaturalPauses checked={naturalPauses} onChange={setNaturalPauses} disabled={working} />
          <EffectsControls value={fx} onChange={setFx} disabled={working} resettable />
          <div>
            <Button disabled={working} onClick={generate}>
              <Play /> {working ? 'Generating…' : 'Generate story'}
            </Button>
          </div>
        </Section>
      )}

      <Section title="From a subtitle file" description="Speak an SRT file in one voice, each line at its time. Lines too long for their time are sped up. Uses the title and language above.">
        <FileDrop file={subtitles} onFile={setSubtitles} accept=".srt" disabled={working} label="Drop an SRT file here or click to choose" />
        <Field label="Voice">
          <VoiceSelect voices={voices} value={subtitleVoice} onChange={setSubtitleVoice} disabled={working} />
        </Field>
        <div>
          <Button variant="outline" disabled={working || !subtitles} onClick={generateFromSubtitles}>
            <Captions /> {working ? 'Generating…' : 'Generate from subtitles'}
          </Button>
        </div>
      </Section>

      <ErrorAlert message={error} />
      {story && working && (
        <Section title="Generating">
          <JobProgress step={story.step} percent={story.percent} hint="You can leave this page; the story appears in Projects when it is ready." />
        </Section>
      )}
      {story?.state === 'error' && <ErrorAlert message={story.error ?? 'Failed'} />}
      {story?.state === 'done' && (
        <Section title={story.title}>
          <AudioResult src={apiUrl(story.audio_url)} download={`${story.title}.wav`} />
        </Section>
      )}
    </PageLayout>
  );
}
