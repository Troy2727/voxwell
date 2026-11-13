import { useEffect, useState } from 'react';
import { House, Search } from 'lucide-react';
import { FEATURES } from '@/features';
import { Button } from '@/components/ui/button';
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';

/* Adapted from Beautiful UI's Search (https://github.com/slev12397/beautiful-ui),
 * MIT License, Copyright (c) 2026 Shane Levine. */

const GROUPS = [...new Set(FEATURES.map((f) => f.group))];
const MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

/** Jump to any page by name: a header button, or Ctrl K / ⌘K from anywhere. */
export function PageSearch({ onOpen }: { onOpen: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const go = (id: string) => {
    onOpen(id);
    setOpen(false);
    setQuery('');
  };

  return (
    <>
      <Button variant="outline" size="sm" className="text-muted-foreground ml-auto h-8 gap-2 px-2.5" aria-label="Search pages" aria-keyshortcuts={MAC ? 'Meta+K' : 'Control+K'} onClick={() => setOpen(true)}>
        <Search />
        <span className="hidden sm:inline">Search pages</span>
        <kbd className="bg-muted hidden rounded border px-1.5 font-mono text-[10px] sm:inline">{MAC ? '⌘K' : 'Ctrl K'}</kbd>
      </Button>
      <CommandDialog open={open} onOpenChange={setOpen} title="Search pages" description="Type a page name, then press Enter to open it.">
        <CommandInput placeholder="Go to a page…" value={query} onValueChange={setQuery} />
        <CommandList>
          <CommandEmpty>
            No page matches “{query}”.
            <br />
            <span className="text-muted-foreground text-xs">Try “dub”, “voice” or “transcribe”.</span>
          </CommandEmpty>
          <CommandGroup heading="Start">
            <CommandItem value="Home" onSelect={() => go('home')}>
              <House /> Home
            </CommandItem>
          </CommandGroup>
          {GROUPS.map((group) => (
            <CommandGroup key={group} heading={group}>
              {FEATURES.filter((f) => f.group === group).map((f) => (
                <CommandItem key={f.id} value={f.title} onSelect={() => go(f.id)}>
                  <f.icon /> {f.title}
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </CommandList>
      </CommandDialog>
    </>
  );
}
