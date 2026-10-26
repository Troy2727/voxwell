import { useEffect, useState } from 'react';
import { Pencil } from 'lucide-react';
import { toast } from 'sonner';
import { apiUrl, listVoices, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ConfirmButton } from '@/components/confirm-button';
import { ErrorAlert, message, Muted, Page as PageLayout } from '@/components/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';

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
    <PageLayout title="Saved voices" description="Every voice you uploaded or designed. Rename, listen or delete.">
      <ErrorAlert message={error} />
      {voices === null && <Skeleton className="h-32 w-full" />}
      {voices?.length === 0 && !error && (
        <Card>
          <CardContent>
            <Muted>No saved voices yet. Upload one in Voice cloning or design one in Voice design.</Muted>
          </CardContent>
        </Card>
      )}
      {voices?.map((v) => (
        <VoiceCard key={v.id} voice={v} onChanged={refresh} onError={(e) => setError(message(e))} />
      ))}
    </PageLayout>
  );
}

function VoiceCard({ voice, onChanged, onError }: { voice: Voice; onChanged: () => void; onError: (e: unknown) => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(voice.name);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    try {
      await action();
      setEditing(false);
      onChanged();
      toast.success(done);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  const rename = () => run(() => sendJson(`/api/voices/${voice.id}`, 'PATCH', { name }), 'Renamed');
  const remove = () => run(() => sendJson(`/api/voices/${voice.id}`, 'DELETE'), `Deleted "${voice.name}"`);

  return (
    <Card className="gap-4 py-4">
      <CardContent className="flex flex-col gap-3 px-4">
        {editing ? (
          <div className="flex items-center gap-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} className="flex-1" autoFocus />
            <Button disabled={busy || !name.trim()} onClick={rename}>Save</Button>
            <Button variant="outline" disabled={busy} onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <h2 className="flex-1 truncate font-semibold">{voice.name}</h2>
            <Badge variant="secondary">{voice.source === 'design' ? 'Designed' : 'Uploaded'}</Badge>
            <Button variant="outline" size="sm" disabled={busy} onClick={() => { setName(voice.name); setEditing(true); }}>
              <Pencil /> Rename
            </Button>
            <ConfirmButton title={`Delete "${voice.name}"?`} disabled={busy} onConfirm={remove}>
              Delete
            </ConfirmButton>
          </div>
        )}
        <AudioResult src={apiUrl(`/api/voices/${voice.id}/audio`)} lazy />
      </CardContent>
    </Card>
  );
}
