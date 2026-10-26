import { useEffect, useState } from 'react';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { LANGUAGES } from '../voice_cloning/languages';

interface Phone {
  enabled: boolean;
  public_url: string;
  auth_token_set: boolean;
  greeting_text: string;
  voice_id: string;
  language: string;
  greeting_ready: boolean;
  gateway: string;
  gateway_running: boolean;
  webhook_url: string;
  calls: { time: number; from: string }[];
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Opt-in: callers to a Twilio number hear a greeting in a Voxwell voice. Off by default. */
export default function PhoneCard() {
  const [phone, setPhone] = useState<Phone | null>(null);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [form, setForm] = useState({ public_url: '', greeting_text: '', voice_id: '', language: 'en' });
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [audioKey, setAudioKey] = useState(0);

  const show = (p: Phone) => {
    setPhone(p);
    setForm({ public_url: p.public_url, greeting_text: p.greeting_text, voice_id: p.voice_id, language: p.language });
  };

  useEffect(() => {
    api<Phone>('/api/integrations/phone').then(show, (e) => setError(message(e)));
    listVoices().then(setVoices, () => setVoices([]));
  }, []);

  async function run(action: () => Promise<Phone>) {
    setBusy(true);
    setError('');
    try {
      show(await action());
      setToken('');
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  const save = (enabled: boolean) =>
    run(() => sendJson<Phone>('/api/integrations/phone', 'PUT', { ...form, enabled, auth_token: token ? token : null }));
  const record = () =>
    run(async () => {
      await sendJson<Phone>('/api/integrations/phone', 'PUT', { ...form, enabled: phone?.enabled ?? false, auth_token: token ? token : null });
      const p = await sendJson<Phone>('/api/integrations/phone/greeting', 'POST');
      setAudioKey((k) => k + 1);
      return p;
    });

  if (!phone) return error ? <p className="error">{error}</p> : null;

  return (
    <div className="card">
      <h2 style={{ margin: 0 }}>Phone calls (Twilio) · optional</h2>
      <p className="meta" style={{ margin: 0 }}>
        People who call your Twilio number hear a greeting spoken in one of your voices. This is <strong>off</strong> unless you
        turn it on. It needs a Twilio account and a tunnel (such as Cloudflare Tunnel or ngrok) that you run yourself; only a
        small separate server with the greeting is exposed, never the rest of Voxwell, and every call must be signed by Twilio.
      </p>

      <label className="field">
        Greeting
        <textarea rows={2} maxLength={500} value={form.greeting_text} disabled={busy}
          onChange={(e) => setForm({ ...form, greeting_text: e.target.value })} placeholder="Hi! You've reached Voxwell. Please call back later." />
      </label>
      <div className="row">
        <label className="field" style={{ flex: 1 }}>
          Voice
          <select value={form.voice_id} disabled={busy} onChange={(e) => setForm({ ...form, voice_id: e.target.value })}>
            <option value="">Default voice</option>
            {voices.map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </select>
        </label>
        <label className="field">
          Language
          <select value={form.language} disabled={busy} onChange={(e) => setForm({ ...form, language: e.target.value })}>
            {LANGUAGES.map(([code, label]) => (
              <option key={code} value={code}>{label}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="row">
        <button className="secondary" disabled={busy || !form.greeting_text.trim()} onClick={record}>
          {busy ? 'Working…' : phone.greeting_ready ? 'Record again' : 'Record greeting'}
        </button>
        {phone.greeting_ready && <audio key={audioKey} controls src={apiUrl(`/api/integrations/phone/greeting.wav?v=${audioKey}`)} />}
      </div>

      <label className="field">
        1. Run a tunnel to this address, then paste the public https address it gives you
        <code>{phone.gateway}</code>
        <input value={form.public_url} disabled={busy} onChange={(e) => setForm({ ...form, public_url: e.target.value })} placeholder="https://your-name.trycloudflare.com" />
      </label>
      <label className="field">
        2. Twilio Auth Token (Twilio Console → Account Info) {phone.auth_token_set && '· saved; type a new one to replace it'}
        <input type="password" autoComplete="off" value={token} disabled={busy} onChange={(e) => setToken(e.target.value)} />
      </label>
      {phone.webhook_url && (
        <div className="field">
          3. In Twilio, set your number's “A call comes in” webhook to (HTTP POST):
          <code>{phone.webhook_url}</code>
        </div>
      )}

      <div className="row">
        {phone.enabled ? (
          <button className="secondary" disabled={busy} onClick={() => save(false)}>Turn off</button>
        ) : (
          <button className="primary" disabled={busy} onClick={() => save(true)}>Turn on</button>
        )}
        <button className="secondary" disabled={busy} onClick={() => save(phone.enabled)}>Save</button>
        <span className="meta">
          {phone.enabled ? (phone.gateway_running ? 'On: answering calls' : 'On: starting…') : 'Off'}
          {phone.enabled && !phone.greeting_ready && ' · record a greeting, or calls just hang up'}
        </span>
      </div>
      {error && <p className="error">{error}</p>}
      {phone.calls.length > 0 && (
        <div className="field">
          Recent calls
          {phone.calls.map((c, i) => (
            <span key={i} className="meta">{new Date(c.time * 1000).toLocaleString()} · from {c.from}</span>
          ))}
        </div>
      )}
    </div>
  );
}
