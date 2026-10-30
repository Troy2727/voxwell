import { useEffect, useRef, useState } from 'react';
import { Play } from 'lucide-react';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { EffectsControls, EffectsSettings, isNeutral, NO_EFFECTS } from '@/components/effects-controls';
import { JobProgress } from '@/components/job-progress';
import { ErrorAlert, Field, message, Muted, Page as PageLayout, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
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

export default function Page() {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [title, setTitle] = useState('');
  const [language, setLanguage] = useState('en');
  const [script, setScript] = useState('');
  const [speakers, setSpeakers] = useState<string[]>([]);
  const [lineCount, setLineCount] = useState(0);
  const [scriptError, setScriptError] = useState('');
  const [cast, setCast] = useState<Record<string, string>>({});
  const [story, setStory] = useState<Story | null>(null);
  const [fx, setFx] = useState<EffectsSettings>(NO_EFFECTS);
  const [error, setError] = useState('');
  const timer = useRef<number | undefined>(undefined);
  const parseTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
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

  async function generate() {
    setError('');
    setStory(null);
    const chosen = Object.fromEntries(speakers.map((s) => [s, cast[s] ?? DEFAULT_VOICE]));
    try {
      const { id } = await sendJson<{ id: string }>('/api/stories/jobs', 'POST', { title, language, script, cast: chosen, effects: isNeutral(fx) ? null : fx });
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
          <Field label="Language">
            <ChoiceSelect options={LANGUAGES} value={language} onChange={setLanguage} />
          </Field>
        </div>
        <Field label="Script" htmlFor="story-script" hint="One line each, as “Name: what they say”. Lines without a name are read by the Narrator.">
          <Textarea id="story-script" rows={10} value={script} placeholder={EXAMPLE} onChange={(e) => setScript(e.target.value)} className="font-mono text-sm" />
        </Field>
        {!script && (
          <div>
            <Button variant="outline" size="sm" onClick={() => setScript(EXAMPLE)}>Use the example</Button>
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
          <EffectsControls value={fx} onChange={setFx} disabled={working} />
          <div>
            <Button disabled={working} onClick={generate}>
              <Play /> {working ? 'Generating…' : 'Generate story'}
            </Button>
          </div>
        </Section>
      )}

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
