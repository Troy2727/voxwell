import { apiUrl, type Voice } from '@/api';
import { VoicePicker, type VoiceOption } from '@/components/ui/voice-picker';

/** Pick a saved voice (with a play preview of its reference clip), or the default voice. */
export function VoiceSelect({ voices, value, onChange, disabled, defaultLabel = 'Default voice', defaultDescription = 'Built into the speech model' }: {
  voices: Voice[] | null;
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  defaultLabel?: string | null;
  defaultDescription?: string;
}) {
  const options: VoiceOption[] = [
    ...(defaultLabel === null ? [] : [{ id: '', name: defaultLabel, description: defaultDescription }]),
    ...(voices ?? []).map((v) => ({
      id: v.id,
      name: v.name,
      description: v.source === 'design' ? 'Designed' : 'Uploaded',
      previewUrl: apiUrl(`/api/voices/${v.id}/audio`),
    })),
  ];
  return (
    <div className={disabled ? 'pointer-events-none opacity-50' : undefined} aria-disabled={disabled}>
      <VoicePicker
        voices={options}
        value={value}
        onValueChange={onChange}
        placeholder="Choose a voice"
        // Look like the other dropdowns (SelectTrigger), not like a button.
        className="border-input dark:bg-input/30 dark:hover:bg-input/50 bg-transparent px-3 font-normal hover:bg-transparent"
      />
    </div>
  );
}
