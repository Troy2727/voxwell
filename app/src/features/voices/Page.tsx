import { useEffect, useState } from 'react';
import { FolderPlus, Library, Pencil, Save, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { apiUrl, listVoiceCollections, listVoices, sendJson, voiceSourceLabel, type Voice, type VoiceCollection } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ConfirmButton } from '@/components/confirm-button';
import { EmptyState, ErrorAlert, message, Page as PageLayout } from '@/components/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { CollectionBar } from './Collections';

export default function Page() {
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [collections, setCollections] = useState<VoiceCollection[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');

  const refresh = () => {
    void listVoiceCollections().then(setCollections, () => setCollections([]));
    return listVoices().then(setVoices, (e) => {
      setVoices([]);
      setError(message(e));
    });
  };
  useEffect(() => {
    void refresh();
  }, []);

  const inCollection = collections.find((c) => c.id === selected);
  const shown = inCollection ? voices?.filter((v) => inCollection.voice_ids.includes(v.id)) : voices;

  return (
    <PageLayout title="Saved voices" description="Every voice you uploaded or designed. Rename, listen, delete or sort them into collections." wide>
      <ErrorAlert message={error} />
      {voices !== null && (
        <CollectionBar
          collections={collections}
          voiceCount={voices.length}
          selected={inCollection ? selected : ''}
          onSelect={setSelected}
          onChanged={refresh}
          onError={(e) => setError(message(e))}
        />
      )}
      {voices === null && <Skeleton className="h-32 w-full" />}
      {voices?.length === 0 && !error && (
        <EmptyState icon={Library} title="No saved voices yet">
          Upload one in Voice cloning, design one in Voice design or add one from the Gallery.
        </EmptyState>
      )}
      {inCollection && shown?.length === 0 && (
        <EmptyState icon={FolderPlus} title={`"${inCollection.name}" is empty`}>
          Use the Collections button on a voice to add it here.
        </EmptyState>
      )}
      {!!shown?.length && (
        <div className="grid items-start gap-4 @4xl:grid-cols-2">
          {shown.map((v) => (
            <VoiceCard key={v.id} voice={v} collections={collections} onChanged={refresh} onError={(e) => setError(message(e))} />
          ))}
        </div>
      )}
    </PageLayout>
  );
}

function VoiceCard({ voice, collections, onChanged, onError }: {
  voice: Voice;
  collections: VoiceCollection[];
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
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

  const toggle = (c: VoiceCollection, add: boolean) =>
    run(() => sendJson(`/api/voice_collections/${c.id}/voices/${voice.id}`, add ? 'PUT' : 'DELETE'), add ? `Added to "${c.name}"` : `Removed from "${c.name}"`);

  return (
    <Card className="gap-4 py-4">
      <CardContent className="flex flex-col gap-3 px-4">
        {editing ? (
          <div className="flex items-center gap-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} className="flex-1" autoFocus />
            <Button disabled={busy || !name.trim()} onClick={rename}><Save /> Save</Button>
            <Button variant="outline" disabled={busy} onClick={() => setEditing(false)}>Cancel</Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {/* A row of its own on a phone, so the actions wrap under it instead of hiding it. */}
            <h2 className="min-w-0 basis-full truncate font-semibold sm:flex-1 sm:basis-auto">{voice.name}</h2>
            <Badge variant="secondary">{voiceSourceLabel(voice.source)}</Badge>
            {collections.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" disabled={busy}>
                    <FolderPlus /> Collections
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>Add to collection</DropdownMenuLabel>
                  {collections.map((c) => (
                    <DropdownMenuCheckboxItem
                      key={c.id}
                      checked={c.voice_ids.includes(voice.id)}
                      onCheckedChange={(checked) => void toggle(c, checked === true)}
                    >
                      {c.name}
                    </DropdownMenuCheckboxItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            <Button variant="outline" size="sm" disabled={busy} onClick={() => { setName(voice.name); setEditing(true); }}>
              <Pencil /> Rename
            </Button>
            <ConfirmButton title={`Delete "${voice.name}"?`} disabled={busy} onConfirm={remove}>
              <Trash2 /> Delete
            </ConfirmButton>
          </div>
        )}
        <AudioResult src={apiUrl(`/api/voices/${voice.id}/audio`)} lazy />
      </CardContent>
    </Card>
  );
}
