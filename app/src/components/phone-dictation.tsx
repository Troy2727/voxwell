import { useState, type FormEvent } from 'react';
import { ExternalLink, Smartphone } from 'lucide-react';
import { ErrorAlert, Muted, Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { readSaved, usePersisted } from '@/lib/persisted';

const SETUP_URL = 'https://github.com/Troy2727/voxwell#-integrations';

/** The address's https origin if it's a Tailscale name, else null, so this link can't be pointed at another site. */
export function phoneAddress(text: string): string | null {
  const trimmed = text.trim();
  try {
    const url = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`);
    return url.protocol === 'https:' && !url.username && !url.password && url.hostname.endsWith('.ts.net') ? url.origin : null;
  } catch {
    return null;
  }
}

const ADDRESS_KEY = 'voxwell.phone.address';

/** The saved private address, checked again in case what's stored was changed; '' if there's none. */
export function savedPhoneAddress(): string {
  const saved = readSaved(ADDRESS_KEY);
  return typeof saved === 'string' ? (phoneAddress(saved) ?? '') : '';
}

/** On a phone this website can't reach the computer by itself. With the computer's private address it can dictate. */
export function PhoneDictation() {
  const [saved, setSaved] = usePersisted(ADDRESS_KEY, '', (value) => (typeof value === 'string' ? (phoneAddress(value) ?? '') : ''));
  const [text, setText] = useState('');
  const [changing, setChanging] = useState(false);
  const [error, setError] = useState('');

  function save(event: FormEvent) {
    event.preventDefault();
    const address = phoneAddress(text);
    if (!address) {
      setError('Enter your computer\'s private address. It ends in .ts.net.');
      return;
    }
    setSaved(address);
    setText('');
    setError('');
    setChanging(false);
  }

  return (
    <Section title="Dictate from your phone" description="Record on the Dictation page while your computer does the work. Your computer must be on, with Voxwell running, and Tailscale on both devices.">
      {saved && !changing ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild>
            <a href={saved}>
              <Smartphone /> Open the private page
            </a>
          </Button>
          <Button variant="outline" onClick={() => setChanging(true)}>Change address</Button>
        </div>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={save}>
          <Input aria-label="Your computer's private address" inputMode="url" autoCapitalize="none" autoCorrect="off" placeholder="https://your-computer.your-network.ts.net" value={text} onChange={(e) => setText(e.target.value)} />
          <div>
            <Button type="submit">Save address</Button>
          </div>
          <ErrorAlert message={error} />
          <Muted className="text-xs">
            On your computer, run <code>voxwell serve --remote</code>. It prints this address.{' '}
            <a className="text-foreground inline-flex items-center gap-1 underline" href={SETUP_URL} target="_blank" rel="noreferrer">
              Setup steps <ExternalLink className="size-3" />
            </a>
          </Muted>
        </form>
      )}
    </Section>
  );
}
