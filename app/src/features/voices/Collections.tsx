import { useState } from 'react';
import { FolderPlus, Pencil } from 'lucide-react';
import { toast } from 'sonner';
import { sendJson, type VoiceCollection } from '../../api';
import { ConfirmButton } from '@/components/confirm-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/** The collection filter row on Saved voices: pick a folder, create one, rename or delete the selected one. */
export function CollectionBar({ collections, voiceCount, selected, onSelect, onChanged, onError }: {
  collections: VoiceCollection[];
  voiceCount: number;
  selected: string;
  onSelect: (id: string) => void;
  onChanged: () => void;
  onError: (e: unknown) => void;
}) {
  const [mode, setMode] = useState<'create' | 'rename' | null>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const current = collections.find((c) => c.id === selected);

  async function submit() {
    setBusy(true);
    try {
      if (mode === 'create') {
        const made = await sendJson<VoiceCollection>('/api/voice_collections', 'POST', { name });
        onSelect(made.id);
        toast.success(`Created "${made.name}"`);
      } else if (current) {
        await sendJson(`/api/voice_collections/${current.id}`, 'PATCH', { name });
        toast.success('Renamed');
      }
      setMode(null);
      onChanged();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!current) return;
    setBusy(true);
    try {
      await sendJson(`/api/voice_collections/${current.id}`, 'DELETE');
      onSelect('');
      onChanged();
      toast.success(`Deleted the collection "${current.name}"`);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant={selected === '' ? 'default' : 'outline'} onClick={() => onSelect('')}>
          All ({voiceCount})
        </Button>
        {collections.map((c) => (
          <Button key={c.id} size="sm" variant={selected === c.id ? 'default' : 'outline'} onClick={() => onSelect(c.id)}>
            {c.name} ({c.voice_ids.length})
          </Button>
        ))}
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setName(''); setMode('create'); }}>
          <FolderPlus /> New collection
        </Button>
      </div>
      {mode ? (
        <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Collection name"
            aria-label="Collection name"
            className="flex-1"
            autoFocus
          />
          <Button type="submit" disabled={busy || !name.trim()}>{mode === 'create' ? 'Create' : 'Save'}</Button>
          <Button type="button" variant="outline" disabled={busy} onClick={() => setMode(null)}>Cancel</Button>
        </form>
      ) : (
        current && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" disabled={busy} onClick={() => { setName(current.name); setMode('rename'); }}>
              <Pencil /> Rename collection
            </Button>
            <ConfirmButton
              title={`Delete the collection "${current.name}"?`}
              description="The voices in it stay saved; only the collection is removed."
              disabled={busy}
              onConfirm={remove}
            >
              Delete collection
            </ConfirmButton>
          </div>
        )
      )}
    </div>
  );
}
