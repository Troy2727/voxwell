import { useCallback, useEffect, useRef, useState } from 'react';
import { apiUrl } from '../../api';

interface TranscribeResult {
  text: string;
  language: string;
}

const LANGUAGES: [string, string][] = [
  ['', 'Auto-detect'], ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'],
  ['it', 'Italian'], ['pt', 'Portuguese'], ['nl', 'Dutch'], ['ru', 'Russian'], ['zh', 'Chinese'],
  ['ja', 'Japanese'], ['ko', 'Korean'], ['ar', 'Arabic'], ['hi', 'Hindi'], ['tr', 'Turkish'],
];

type Phase = 'idle' | 'recording' | 'transcribing';

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

export default function Page() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [language, setLanguage] = useState('');
  const [text, setText] = useState('');
  const [history, setHistory] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number>();
  const viaShortcut = useRef(false);
  const phaseRef = useRef<Phase>('idle');
  const languageRef = useRef(language);
  languageRef.current = language;

  const setPhaseBoth = (p: Phase) => {
    phaseRef.current = p;
    setPhase(p);
  };

  const transcribe = useCallback(async (blob: Blob, deliver: boolean) => {
    setPhaseBoth('transcribing');
    try {
      const form = new FormData();
      form.append('file', blob, 'recording.webm');
      if (languageRef.current) form.append('language', languageRef.current);
      const res = await fetch(apiUrl('/api/dictation/transcribe'), { method: 'POST', body: form });
      if (!res.ok) {
        let msg = `${res.status}`;
        try {
          msg = (await res.json()).detail ?? msg;
        } catch {
          /* keep status */
        }
        throw new Error(msg);
      }
      const result = (await res.json()) as TranscribeResult;
      setText(result.text);
      if (result.text) {
        setHistory((h) => [result.text, ...h].slice(0, 20));
        if (deliver) await window.voxwell?.dictation.deliver(result.text);
      } else {
        setError('No speech detected.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPhaseBoth('idle');
    }
  }, []);

  const start = useCallback(
    async (fromShortcut: boolean) => {
      setError('');
      setCopied(false);
      viaShortcut.current = fromShortcut;
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        const name = e instanceof DOMException ? e.name : '';
        setError(
          name === 'NotAllowedError'
            ? 'Microphone access was denied. Allow it in your system or browser settings and try again.'
            : name === 'NotFoundError'
              ? 'No microphone found.'
              : `Could not open the microphone: ${e instanceof Error ? e.message : String(e)}`,
        );
        return;
      }
      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (ev) => {
        if (ev.data.size) chunks.push(ev.data);
      };
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        window.clearInterval(timer.current);
        void transcribe(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }), viaShortcut.current);
      };
      recorder.current = rec;
      rec.start();
      setElapsed(0);
      timer.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
      setPhaseBoth('recording');
    },
    [transcribe],
  );

  const toggle = useCallback(
    (fromShortcut: boolean) => {
      if (phaseRef.current === 'recording') {
        if (recorder.current?.state === 'recording') recorder.current.stop();
      } else if (phaseRef.current === 'idle') {
        void start(fromShortcut);
      }
    },
    [start],
  );

  useEffect(() => window.voxwell?.dictation.onToggle(() => toggle(true)), [toggle]);
  useEffect(
    () => () => {
      window.clearInterval(timer.current);
      const rec = recorder.current;
      if (rec?.state === 'recording') {
        rec.onstop = null;
        rec.stream.getTracks().forEach((t) => t.stop());
        rec.stop();
      }
    },
    [],
  );

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      setError('Could not copy to the clipboard.');
    }
  };

  const recording = phase === 'recording';
  return (
    <section className="page">
      <h1>Dictation</h1>
      <div className="card">
        <div className="row">
          <button className="primary" disabled={phase === 'transcribing'} onClick={() => toggle(false)}>
            {recording ? 'Stop' : 'Record'}
          </button>
          {recording && <span aria-live="polite">● Recording {fmt(elapsed)}</span>}
          {phase === 'transcribing' && <span aria-live="polite">Transcribing…</span>}
          <label className="field">
            Language
            <select value={language} disabled={phase !== 'idle'} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <small>
          {window.voxwell
            ? 'Press Ctrl/Cmd+Shift+Space anywhere to start and stop; the text is copied for you to paste.'
            : 'The global shortcut is available in the desktop app.'}
        </small>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>

      <div className="card">
        <h2>Result</h2>
        {text ? (
          <>
            <p>{text}</p>
            <div className="row">
              <button onClick={() => copy(text)}>{copied ? 'Copied' : 'Copy'}</button>
            </div>
          </>
        ) : (
          <p>Nothing yet. Press Record and speak.</p>
        )}
      </div>

      <div className="card">
        <h2>Recent</h2>
        {history.length === 0 ? (
          <p>No transcripts yet.</p>
        ) : (
          history.map((h, i) => (
            <div className="row" key={i}>
              <span style={{ flex: 1 }}>{h}</span>
              <button onClick={() => copy(h)}>Copy</button>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
