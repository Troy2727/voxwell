import { useEffect, useState } from 'react';
import { Mic, Phone, PhoneOff, Save } from 'lucide-react';
import { api, apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { ErrorAlert, Field, message, Muted, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
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

  if (!phone) return <ErrorAlert message={error} />;

  const status = phone.enabled ? (phone.gateway_running ? 'On: answering calls' : 'On: starting…') : 'Off';

  return (
    <Section
      title="Phone calls (Twilio) · optional"
      description={
        <>
          People who call your Twilio number hear a greeting spoken in one of your voices. This is <strong>off</strong> unless you
          turn it on. It needs a Twilio account and a tunnel (such as Cloudflare Tunnel or ngrok) that you run yourself; only a
          small separate server with the greeting is exposed, never the rest of Voxwell, and every call must be signed by Twilio.
        </>
      }
      action={<Badge className={phone.enabled ? 'bg-success text-white' : undefined} variant={phone.enabled ? 'default' : 'secondary'}>{phone.enabled ? 'On' : 'Off'}</Badge>}
    >
      <Field label="Greeting" htmlFor="phone-greeting">
        <Textarea id="phone-greeting" rows={2} maxLength={500} value={form.greeting_text} disabled={busy}
          onChange={(e) => setForm({ ...form, greeting_text: e.target.value })} placeholder="Hi! You've reached Voxwell. Please call back later." />
      </Field>
      <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
        <Field label="Voice">
          <VoiceSelect voices={voices} value={form.voice_id} disabled={busy} onChange={(voice_id) => setForm({ ...form, voice_id })} />
        </Field>
        <Field label="Language">
          <ChoiceSelect options={LANGUAGES} value={form.language} disabled={busy} onChange={(language) => setForm({ ...form, language })} />
        </Field>
      </div>
      <div>
        <Button variant="outline" disabled={busy || !form.greeting_text.trim()} onClick={record}>
          <Mic /> {busy ? 'Working…' : phone.greeting_ready ? 'Record again' : 'Record greeting'}
        </Button>
      </div>
      {phone.greeting_ready && <AudioResult key={audioKey} src={apiUrl(`/api/integrations/phone/greeting.wav?v=${audioKey}`)} />}

      <Field label="1. Run a tunnel to this address, then paste the public https address it gives you" htmlFor="phone-url">
        <code className="self-start">{phone.gateway}</code>
        <Input id="phone-url" value={form.public_url} disabled={busy} onChange={(e) => setForm({ ...form, public_url: e.target.value })} placeholder="https://your-name.trycloudflare.com" />
      </Field>
      <Field label={<>2. Twilio Auth Token (Twilio Console → Account Info) {phone.auth_token_set && <Muted className="inline text-xs">· saved; type a new one to replace it</Muted>}</>} htmlFor="phone-token">
        <Input id="phone-token" type="password" autoComplete="off" value={token} disabled={busy} onChange={(e) => setToken(e.target.value)} />
      </Field>
      {phone.webhook_url && (
        <Field label="3. In Twilio, set your number's “A call comes in” webhook to (HTTP POST):">
          <code className="self-start break-all">{phone.webhook_url}</code>
        </Field>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {phone.enabled ? (
          <Button variant="outline" disabled={busy} onClick={() => save(false)}><PhoneOff /> Turn off</Button>
        ) : (
          <Button disabled={busy} onClick={() => save(true)}><Phone /> Turn on</Button>
        )}
        <Button variant="outline" disabled={busy} onClick={() => save(phone.enabled)}><Save /> Save</Button>
        {phone.enabled && (
          <Muted>
            {status}
            {!phone.greeting_ready && ' · record a greeting, or calls just hang up'}
          </Muted>
        )}
      </div>
      <ErrorAlert message={error} />
      {phone.calls.length > 0 && (
        <Field label="Recent calls">
          <div className="divide-y rounded-lg border px-3">
            {phone.calls.map((c, i) => (
              <div key={i} className="text-muted-foreground py-2 text-sm">
                {new Date(c.time * 1000).toLocaleString()} · from {c.from}
              </div>
            ))}
          </div>
        </Field>
      )}
    </Section>
  );
}
