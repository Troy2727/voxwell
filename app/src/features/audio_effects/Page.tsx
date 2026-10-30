import { useState } from 'react';
import { RotateCcw, Sparkles } from 'lucide-react';
import { api, apiUrl } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { EffectsControls, EffectsSettings, isNeutral, NO_EFFECTS } from '@/components/effects-controls';
import { FileDrop } from '@/components/file-drop';
import { ErrorAlert, message, Page as PageLayout, Section } from '@/components/page';
import { Button } from '@/components/ui/button';

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [fx, setFx] = useState<EffectsSettings>(NO_EFFECTS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [audioUrl, setAudioUrl] = useState('');

  async function apply() {
    if (!file) return;
    setBusy(true);
    setError('');
    setAudioUrl('');
    try {
      const body = new FormData();
      body.append('file', file);
      for (const [key, value] of Object.entries(fx)) body.append(key, String(value));
      const res = await api<{ url: string }>('/api/audio_effects/apply', { method: 'POST', body });
      setAudioUrl(apiUrl(res.url));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageLayout title="Audio effects" description="Add reverb, distance, background noise or stereo pan to a recording. The same controls are in Voice cloning and Stories.">
      <Section title="Recording" description="WAV, MP3, FLAC or OGG.">
        <FileDrop file={file} onFile={setFile} accept=".wav,.mp3,.flac,.ogg,audio/*" disabled={busy} />
      </Section>
      <Section title="Effects">
        <EffectsControls value={fx} onChange={setFx} disabled={busy} />
        <div className="flex gap-2">
          <Button disabled={busy || !file} onClick={apply}>
            <Sparkles /> {busy ? 'Processing…' : 'Apply effects'}
          </Button>
          <Button variant="outline" disabled={busy || isNeutral(fx)} onClick={() => setFx(NO_EFFECTS)}>
            <RotateCcw /> Reset
          </Button>
        </div>
        <ErrorAlert message={error} />
        {audioUrl && <AudioResult src={audioUrl} download="voxwell-effects.wav" />}
      </Section>
    </PageLayout>
  );
}
