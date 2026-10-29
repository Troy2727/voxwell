import { ChoiceSelect } from '@/components/choice-select';
import { Field } from '@/components/page';
import { Slider } from '@/components/ui/slider';

export interface EffectsSettings {
  reverb: number;
  distance: number;
  noise: number;
  noise_color: 'pink' | 'brown';
  pan: number;
}

/** Every effect off: the audio comes out exactly as generated. */
export const NO_EFFECTS: EffectsSettings = { reverb: 0, distance: 0, noise: 0, noise_color: 'pink', pan: 0 };

export const isNeutral = (fx: EffectsSettings) => fx.reverb === 0 && fx.distance === 0 && fx.noise === 0 && fx.pan === 0;

const NOISE_COLORS: [string, string][] = [['pink', 'Pink (hiss)'], ['brown', 'Brown (rumble)']];

function panLabel(pan: number) {
  if (pan === 0) return 'center';
  return `${Math.round(Math.abs(pan) * 100)}% ${pan < 0 ? 'left' : 'right'}`;
}

/** Sliders for reverb, distance, background noise and pan; the settings match the backend's Effects model. */
export function EffectsControls({ value, onChange, disabled }: { value: EffectsSettings; onChange: (fx: EffectsSettings) => void; disabled?: boolean }) {
  const set = (patch: Partial<EffectsSettings>) => onChange({ ...value, ...patch });
  const percent = (v: number) => `${Math.round(v * 100)}%`;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label={`Reverb: ${percent(value.reverb)}`}>
        <Slider min={0} max={1} step={0.05} value={[value.reverb]} onValueChange={([v]) => set({ reverb: v })} disabled={disabled} aria-label="Reverb" className="py-2" />
      </Field>
      <Field label={`Distance: ${percent(value.distance)}`} hint="Farther sounds duller, quieter and more echoey.">
        <Slider min={0} max={1} step={0.05} value={[value.distance]} onValueChange={([v]) => set({ distance: v })} disabled={disabled} aria-label="Distance" className="py-2" />
      </Field>
      <Field label={`Background noise: ${percent(value.noise)}`}>
        <Slider min={0} max={1} step={0.05} value={[value.noise]} onValueChange={([v]) => set({ noise: v })} disabled={disabled} aria-label="Background noise" className="py-2" />
      </Field>
      <Field label="Noise type">
        <ChoiceSelect options={NOISE_COLORS} value={value.noise_color} onChange={(v) => set({ noise_color: v as EffectsSettings['noise_color'] })} disabled={disabled} />
      </Field>
      <Field label={`Pan: ${panLabel(value.pan)}`} hint="Any pan other than center makes the audio stereo.">
        <Slider min={-1} max={1} step={0.05} value={[value.pan]} onValueChange={([v]) => set({ pan: v })} disabled={disabled} aria-label="Pan" className="py-2" />
      </Field>
    </div>
  );
}
