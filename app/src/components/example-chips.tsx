import { Button } from '@/components/ui/button';

/** Ready-made prompts the user can click to fill a text box. */
export function ExampleChips({ examples, onPick, disabled }: { examples: readonly string[]; onPick: (example: string) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-wrap gap-2">
      {examples.map((ex) => (
        <Button
          key={ex}
          type="button"
          variant="secondary"
          size="sm"
          disabled={disabled}
          className="h-auto max-w-full py-1.5 text-left whitespace-normal"
          onClick={() => onPick(ex)}
        >
          {ex}
        </Button>
      ))}
    </div>
  );
}
