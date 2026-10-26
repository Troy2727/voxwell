import { useEffect, useRef, useState } from 'react';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
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
const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

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
      const { id } = await sendJson<{ id: string }>('/api/stories/jobs', 'POST', { title, language, script, cast: chosen });
      await poll(id);
    } catch (e) {
      setError(message(e));
    }
  }

  const working = story?.state === 'queued' || story?.state === 'running';

  return (
    <section className="page">
      <h1>Stories</h1>
      <div className="card">
        <div className="row">
          <label className="field" style={{ flex: 1 }}>
            Title (optional)
            <input value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="field">
            Language
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map(([code, label]) => (
                <option key={code} value={code}>{label}</option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          Script: one line each, as “Name: what they say”. Lines without a name are read by the Narrator.
          <textarea rows={10} value={script} placeholder={EXAMPLE} onChange={(e) => setScript(e.target.value)} />
        </label>
        {!script && (
          <div className="row">
            <button className="secondary" onClick={() => setScript(EXAMPLE)}>Use the example</button>
          </div>
        )}
        {scriptError && <p className="error">{scriptError}</p>}
      </div>

      {speakers.length > 0 && !scriptError && (
        <div className="card">
          <h2>Cast</h2>
          <p className="meta">{lineCount} line(s). Give each speaker a voice from Saved voices.</p>
          {speakers.map((speaker) => (
            <label key={speaker} className="row">
              <span style={{ minWidth: 140 }}>{speaker}</span>
              <select value={cast[speaker] ?? DEFAULT_VOICE} onChange={(e) => setCast({ ...cast, [speaker]: e.target.value })} style={{ flex: 1 }}>
                <option value={DEFAULT_VOICE}>Default voice</option>
                {voices.map((v) => (
                  <option key={v.id} value={v.id}>{v.name}</option>
                ))}
              </select>
            </label>
          ))}
          {voices.length === 0 && <small className="meta">No saved voices yet; everyone uses the default voice.</small>}
          <div className="row">
            <button className="primary" disabled={working} onClick={generate}>
              {working ? 'Generating…' : 'Generate story'}
            </button>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}
      {story && working && (
        <div className="card">
          <div>{story.step}</div>
          <progress max={100} value={story.percent} style={{ width: '100%' }} />
          <small className="meta">You can leave this page; the story appears in Projects when it is ready.</small>
        </div>
      )}
      {story?.state === 'error' && <p className="error">{story.error}</p>}
      {story?.state === 'done' && (
        <div className="card">
          <h2 style={{ margin: 0 }}>{story.title}</h2>
          <audio controls src={apiUrl(story.audio_url)} />
          <a href={apiUrl(story.audio_url)} download={`${story.title}.wav`}>Download WAV</a>
        </div>
      )}
    </section>
  );
}
