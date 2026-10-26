import { useEffect, useState } from 'react';
import { api, apiUrl, sendJson, type Voice } from '../../api';

interface Preset {
  id: string;
  name: string;
  category: string;
  description: string;
  sample: string;
  ready: boolean;
  audio_url: string | null;
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Page() {
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api<Preset[]>('/api/gallery/presets').then(setPresets, (e) => {
      setPresets([]);
      setError(message(e));
    });
  }, []);

  const replace = (p: Preset) => setPresets((list) => list?.map((x) => (x.id === p.id ? p : x)) ?? null);
  const categories = [...new Set(presets?.map((p) => p.category))];

  return (
    <section className="page">
      <h1>Gallery</h1>
      <p className="meta">
        Ready-made voices, created on your computer from a description. Listen to one, then add it to Saved voices
        to use it anywhere. The first listen takes a little while.
      </p>
      {error && <p className="error">{error}</p>}
      {presets === null && <p className="meta">Loading…</p>}
      {categories.map((category) => (
        <div key={category} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <h2 style={{ margin: '8px 0 0' }}>{category}</h2>
          {presets?.filter((p) => p.category === category).map((p) => (
            <PresetCard key={p.id} preset={p} onUpdated={replace} />
          ))}
        </div>
      ))}
    </section>
  );
}

function PresetCard({ preset, onUpdated }: { preset: Preset; onUpdated: (p: Preset) => void }) {
  const [busy, setBusy] = useState<'listen' | 'add' | null>(null);
  const [added, setAdded] = useState<Voice | null>(null);
  const [error, setError] = useState('');

  async function listen() {
    setBusy('listen');
    setError('');
    try {
      onUpdated(await sendJson<Preset>(`/api/gallery/presets/${preset.id}/sample`, 'POST'));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  async function add() {
    setBusy('add');
    setError('');
    try {
      setAdded(await sendJson<Voice>(`/api/gallery/presets/${preset.id}/add`, 'POST', {}));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card">
      <h2 style={{ margin: 0 }}>{preset.name}</h2>
      <p className="meta" style={{ margin: 0 }}>{preset.description}</p>
      {preset.audio_url ? (
        <audio controls autoPlay={busy === null && !added} src={apiUrl(preset.audio_url)} />
      ) : (
        <p className="meta" style={{ margin: 0 }}>“{preset.sample}”</p>
      )}
      <div className="row">
        {!preset.ready && (
          <button className="primary" disabled={busy !== null} onClick={listen}>
            {busy === 'listen' ? 'Creating the voice…' : 'Listen'}
          </button>
        )}
        {preset.ready && (
          <button className="secondary" disabled={busy !== null} onClick={add}>
            {busy === 'add' ? 'Adding…' : 'Add to my voices'}
          </button>
        )}
        {added && <span className="meta">Added as “{added.name}” in Saved voices.</span>}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
