import { useEffect, useState } from 'react';
import { Check, Headphones, Plus } from 'lucide-react';
import { api, apiUrl, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ErrorAlert, message, Page as PageLayout } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

interface Preset {
  id: string;
  name: string;
  category: string;
  description: string;
  sample: string;
  ready: boolean;
  audio_url: string | null;
}

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
    <PageLayout
      title="Gallery"
      description="Ready-made voices, created on your computer from a description. Listen to one, then add it to Saved voices to use it anywhere. The first listen takes a little while."
    >
      <ErrorAlert message={error} />
      {presets === null && <Skeleton className="h-40 w-full" />}
      {categories.map((category) => (
        <div key={category} className="flex flex-col gap-3">
          <h2 className="text-muted-foreground text-sm font-medium tracking-wide uppercase">{category}</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {presets?.filter((p) => p.category === category).map((p) => (
              <PresetCard key={p.id} preset={p} onUpdated={replace} />
            ))}
          </div>
        </div>
      ))}
    </PageLayout>
  );
}

function PresetCard({ preset, onUpdated }: { preset: Preset; onUpdated: (p: Preset) => void }) {
  const [busy, setBusy] = useState<'listen' | 'add' | null>(null);
  const [added, setAdded] = useState<Voice | null>(null);
  const [listened, setListened] = useState(false);
  const [error, setError] = useState('');

  async function listen() {
    setBusy('listen');
    setError('');
    try {
      onUpdated(await sendJson<Preset>(`/api/gallery/presets/${preset.id}/sample`, 'POST'));
      setListened(true);
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
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>{preset.name}</CardTitle>
        <CardDescription>{preset.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        {preset.audio_url ? (
          <AudioResult src={apiUrl(preset.audio_url)} autoPlay={listened} />
        ) : (
          <p className="text-muted-foreground text-sm italic">“{preset.sample}”</p>
        )}
        <ErrorAlert message={error} />
      </CardContent>
      <CardFooter className="flex-wrap gap-2">
        {!preset.ready && (
          <Button disabled={busy !== null} onClick={listen}>
            <Headphones /> {busy === 'listen' ? 'Creating the voice…' : 'Listen'}
          </Button>
        )}
        {preset.ready && !added && (
          <Button variant="outline" disabled={busy !== null} onClick={add}>
            <Plus /> {busy === 'add' ? 'Adding…' : 'Add to my voices'}
          </Button>
        )}
        {added && (
          <span className="text-success flex items-center gap-1 text-sm">
            <Check className="size-4" /> Added as “{added.name}” in Saved voices.
          </span>
        )}
      </CardFooter>
    </Card>
  );
}
