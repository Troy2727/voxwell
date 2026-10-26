import { useState } from 'react';
import { api, apiUrl, type Voice } from '../../api';

const EXAMPLES = [
  'Warm, low female voice, slight British accent, calm pace',
  'Energetic young male narrator, clear and upbeat',
  'Deep, gravelly older man, slow and thoughtful',
];

interface Preview {
  preview_id: string;
  url: string;
}

const post = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Page() {
  const [description, setDescription] = useState('');
  const [sampleText, setSampleText] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Voice | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setLoading(true);
    setError(null);
    setSaved(null);
    try {
      setPreview(await post<Preview>('/api/voice_design/preview', { description, sample_text: sampleText || undefined }));
    } catch (e) {
      setError(message(e));
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    if (!preview) return;
    setSaving(true);
    setError(null);
    try {
      setSaved(await post<Voice>('/api/voice_design/save', { preview_id: preview.preview_id, name }));
    } catch (e) {
      setError(message(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="page">
      <h1>Voice design</h1>
      <div className="card">
        <label className="field">
          Describe the voice
          <textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" onClick={() => setDescription(ex)}>
              {ex}
            </button>
          ))}
        </div>
        <label className="field">
          Sample text (optional)
          <textarea rows={2} value={sampleText} onChange={(e) => setSampleText(e.target.value)} />
        </label>
        <div className="row">
          <button className="primary" onClick={generate} disabled={loading || !description.trim()}>
            {loading ? 'Generating...' : preview ? 'Regenerate' : 'Preview'}
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {preview && (
        <div className="card">
          <audio controls src={apiUrl(preview.url)} />
          <div className="row">
            <label className="field" style={{ flex: 1 }}>
              Voice name
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <button className="primary" onClick={save} disabled={saving || !name.trim()}>
              {saving ? 'Saving...' : 'Save to voices'}
            </button>
          </div>
          {saved && <p>Saved "{saved.name}" to your voices.</p>}
        </div>
      )}
    </section>
  );
}
