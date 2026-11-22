import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { api } from '../../api';
import { ErrorAlert, message, Section } from '@/components/page';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';

interface Setting {
  enabled: boolean;
  device: 'cuda' | 'mps' | 'cpu';
}

const ENDPOINT = '/api/voice_cloning/free-the-gpu';

/** Free the GPU: move the speech model to system RAM while Voxwell is idle. */
export function FreeTheGpu() {
  const [setting, setSetting] = useState<Setting | null>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<Setting>(ENDPOINT).then(setSetting, (e) => setError(message(e)));
  }, []);

  const change = (enabled: boolean) => {
    if (!setting) return;
    const before = setting;
    setSetting({ ...setting, enabled });
    setSaving(true);
    api<Setting>(ENDPOINT, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) })
      .then(setSetting, () => {
        setSetting(before);
        toast.error("Couldn't save this setting. Try again.");
      })
      .finally(() => setSaving(false));
  };

  return (
    <Section title="Free the GPU">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <Switch id="free-the-gpu" checked={setting?.enabled ?? false} disabled={!setting || saving} onCheckedChange={change} />
          <Label htmlFor="free-the-gpu">Move the speech model to system RAM when idle</Label>
        </div>
        <p className="text-muted-foreground text-xs">
          {setting?.device === 'cpu'
            ? 'This computer generates speech on the processor, so the model already lives in system RAM and this has no effect.'
            : 'Frees graphics memory for other apps once Voxwell has finished speaking. The next take moves the model back, which adds a few seconds. Applies to every Voxwell feature that speaks.'}
        </p>
      </div>
      <ErrorAlert message={error} />
    </Section>
  );
}
