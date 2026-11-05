import { useEffect, useState } from 'react';
import { apiUrl, listVoiceCollections, voiceSourceLabel, type Voice, type VoiceCollection } from '@/api';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { VoicePicker, type VoiceOption } from '@/components/ui/voice-picker';
import { readSaved, writeSaved } from '@/lib/persisted';

const RECENT_KEY = 'voxwell.voices.recent';
const MAX_RECENT = 5;

const recentVoices = () => {
  const saved = readSaved(RECENT_KEY);
  return Array.isArray(saved) ? (saved as string[]) : [];
};

/** Pick a saved voice (with a play preview of its reference clip), or the default voice. */
export function VoiceSelect({ voices, value, onChange, disabled, defaultLabel = 'Default voice', defaultDescription = 'Built into the speech model' }: {
  voices: Voice[] | null;
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  defaultLabel?: string | null;
  defaultDescription?: string;
}) {
  const [collections, setCollections] = useState<VoiceCollection[]>([]);
  const [collectionId, setCollectionId] = useState('');
  useEffect(() => {
    listVoiceCollections().then(setCollections, () => setCollections([]));
  }, []);
  // Filter by collection, but never hide the voice that is currently chosen.
  const collection = collections.find((c) => c.id === collectionId);
  const visible = collection ? (voices ?? []).filter((v) => collection.voice_ids.includes(v.id) || v.id === value) : voices;

  // Recently used voices first. Read at each render, as a page can have several of these pickers.
  const recent = recentVoices();
  const rank = (id: string) => (recent.includes(id) ? recent.indexOf(id) : recent.length);
  const options: VoiceOption[] = [
    ...(defaultLabel === null ? [] : [{ id: '', name: defaultLabel, description: defaultDescription }]),
    ...[...(visible ?? [])].sort((a, b) => rank(a.id) - rank(b.id)).map((v) => ({
      id: v.id,
      name: v.name,
      description: `${recent.includes(v.id) ? 'Recent · ' : ''}${voiceSourceLabel(v.source)}`,
      previewUrl: apiUrl(`/api/voices/${v.id}/audio`),
    })),
  ];
  const choose = (id: string) => {
    if (id) writeSaved(RECENT_KEY, [id, ...recent.filter((other) => other !== id)].slice(0, MAX_RECENT));
    onChange(id);
  };
  return (
    <div className={disabled ? 'pointer-events-none opacity-50' : undefined} aria-disabled={disabled}>
      {collections.length > 0 && (
        <Select value={collection ? collectionId : 'all'} onValueChange={(v) => setCollectionId(v === 'all' ? '' : v)}>
          <SelectTrigger size="sm" className="mb-2 w-full" aria-label="Filter voices by collection">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All voices</SelectItem>
            {collections.map((c) => (
              <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      <VoicePicker
        voices={options}
        value={value}
        onValueChange={choose}
        placeholder="Choose a voice"
        // Look like the other dropdowns (SelectTrigger), not like a button.
        className="border-input dark:bg-input/30 dark:hover:bg-input/50 bg-transparent px-3 font-normal hover:bg-transparent"
      />
    </div>
  );
}
