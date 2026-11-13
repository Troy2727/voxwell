import { Drama } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

/** The `cues` object of GET /api/voice_cloning/status. */
export type Cues = {
  languages: string[];
  available: boolean;
  groups: { label: string; tags: { tag: string; label: string }[] }[];
};

/** A "Cues" menu: picking one hands its tag ("[laugh]") to `onPick`. */
export function CuePicker({ groups, disabled, onPick }: { groups: Cues['groups']; disabled?: boolean; onPick: (tag: string) => void }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="max-w-full" disabled={disabled}>
          <Drama /> Cues
        </Button>
      </DropdownMenuTrigger>
      {/* Keep focus off the button on close: the text box takes it, with the cursor after the tag. */}
      <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto" onCloseAutoFocus={(e) => e.preventDefault()}>
        {groups.map((group, i) => (
          <DropdownMenuGroup key={group.label}>
            {i > 0 && <DropdownMenuSeparator />}
            <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
            {group.tags.map(({ tag, label }) => (
              <DropdownMenuItem key={tag} onSelect={() => onPick(`[${tag}]`)}>
                {label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
