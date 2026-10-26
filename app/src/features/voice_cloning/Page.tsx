import { useEffect, useState } from 'react';
import { api, apiUrl, listVoices, Voice } from '../../api';
import { LANGUAGES } from './languages';

export default function Page() {
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [voiceId, setVoiceId] = useState('');
  const [name, setName] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [text, setText] = useState('');
  const [language, setLanguage] = useState('en');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [audioUrl, setAudioUrl] = useState('');

  const refresh = () =>
    listVoices().then(setVoices, (e: Error) => {
      setVoices([]);
      setError(e.message);
    });
  useEffect(() => {
    void refresh();
  }, []);

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
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function generate() {
    setBusy(true);
    setError('');
    setAudioUrl('');
    try {
      const res = await api<{ id: string; url: string }>('/api/voice_cloning/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, language, voice_id: voiceId || null }),
      });
      setAudioUrl(apiUrl(res.url));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page">
      <h1>Voice cloning</h1>

      <div className="card">
        <h2>Add a voice</h2>
        <label className="field">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="My voice" />
        </label>
        <label className="field">
          Reference clip (WAV, MP3, FLAC or OGG; a few seconds of clean speech)
          <input key={uploading ? 'u' : 'i'} type="file" accept=".wav,.mp3,.flac,.ogg,audio/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <div className="row">
          <button className="primary" disabled={uploading || !file || !name.trim()} onClick={upload}>
            {uploading ? 'Uploading…' : 'Upload voice'}
          </button>
        </div>
      </div>

      <div className="card">
        <h2>Generate speech</h2>
        <label className="field">
          Voice
          <select value={voiceId} onChange={(e) => setVoiceId(e.target.value)} disabled={voices === null}>
            <option value="">Default voice</option>
            {(voices ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                {v.name} ({v.source === 'design' ? 'designed' : 'uploaded'})
              </option>
            ))}
          </select>
          {voices !== null && voices.length === 0 && <span>No saved voices yet. Upload one above.</span>}
        </label>
        <label className="field">
          Language
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map(([code, label]) => (
              <option key={code} value={code}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Text
          <textarea rows={5} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <div className="row">
          <button className="primary" disabled={busy || !text.trim()} onClick={generate}>
            {busy ? 'Generating…' : 'Generate'}
          </button>
        </div>
        {error && <div className="error">{error}</div>}
        {audioUrl && (
          <>
            <audio controls src={audioUrl} />
            <a href={audioUrl} download="voxwell-speech.wav">
              Download WAV
            </a>
          </>
        )}
      </div>
    </section>
  );
}
