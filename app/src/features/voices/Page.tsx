import { useEffect, useState } from 'react';
import { apiUrl, listVoices, sendJson, type Voice } from '../../api';

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Page() {
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [error, setError] = useState('');

  const refresh = () =>
    listVoices().then(setVoices, (e) => {
      setVoices([]);
      setError(message(e));
    });
  useEffect(() => {
    void refresh();
  }, []);

  return (
    <section className="page">
      <h1>Saved voices</h1>
      {error && <p className="error">{error}</p>}
      {voices === null && <p className="meta">Loading…</p>}
      {voices?.length === 0 && !error && (
        <div className="card">
          <p>No saved voices yet. Upload one in Voice cloning or design one in Voice design.</p>
        </div>
      )}
      {voices?.map((v) => (
        <VoiceCard key={v.id} voice={v} onChanged={refresh} onError={(e) => setError(message(e))} />
      ))}
    </section>
  );
}

function VoiceCard({ voice, onChanged, onError }: { voice: Voice; onChanged: () => void; onError: (e: unknown) => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(voice.name);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      setEditing(false);
      onChanged();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  const rename = () => run(() => sendJson(`/api/voices/${voice.id}`, 'PATCH', { name }));
  const remove = () => {
    if (window.confirm(`Delete "${voice.name}"? This cannot be undone.`)) void run(() => sendJson(`/api/voices/${voice.id}`, 'DELETE'));
  };

  return (
    <div className="card">
      {editing ? (
        <div className="row">
          <input value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} autoFocus />
          <button className="primary" disabled={busy || !name.trim()} onClick={rename}>
            Save
          </button>
          <button className="secondary" disabled={busy} onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="row">
          <h2 style={{ flex: 1, margin: 0 }}>{voice.name}</h2>
          <span className="meta">{voice.source === 'design' ? 'Designed' : 'Uploaded'}</span>
        </div>
      )}
      <audio controls preload="none" src={apiUrl(`/api/voices/${voice.id}/audio`)} />
      {!editing && (
        <div className="row">
          <button className="secondary" disabled={busy} onClick={() => { setName(voice.name); setEditing(true); }}>
            Rename
          </button>
          <button className="secondary danger" disabled={busy} onClick={remove}>
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
