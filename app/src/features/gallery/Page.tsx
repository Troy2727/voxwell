import { useEffect, useState } from 'react';
import { Check, Headphones, Plus, Search, Star } from 'lucide-react';
import { api, apiUrl, sendJson, type Voice } from '../../api';
import { AudioResult } from '@/components/audio-result';
import { ChoiceSelect } from '@/components/choice-select';
import { EmptyState, ErrorAlert, Field, message, Page as PageLayout } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { usePersisted } from '@/lib/persisted';
import { cn } from '@/lib/utils';

interface Preset {
  id: string;
  name: string;
  category: string;
  gender: string;
  description: string;
  sample: string;
  ready: boolean;
  audio_url: string | null;
}

const GENDERS: [string, string][] = [['all', 'All voices'], ['Female', 'Female'], ['Male', 'Male']];

export default function Page() {
  const [presets, setPresets] = useState<Preset[] | null>(null);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [gender, setGender] = useState('all');
  const [favorites, setFavorites] = usePersisted<string[]>('voxwell.gallery.favorites', []);
  const [onlyFavorites, setOnlyFavorites] = useState(false);

  useEffect(() => {
    api<Preset[]>('/api/gallery/presets').then(setPresets, (e) => {
      setPresets([]);
      setError(message(e));
    });
  }, []);

  const replace = (p: Preset) => setPresets((list) => list?.map((x) => (x.id === p.id ? p : x)) ?? null);
  const categories = [...new Set(presets?.map((p) => p.category))];
  const words = search.trim().toLowerCase();
  const visible = presets?.filter(
    (p) =>
      (category === 'all' || p.category === category) &&
      (gender === 'all' || p.gender === gender) &&
      (!onlyFavorites || favorites.includes(p.id)) &&
      `${p.name} ${p.category} ${p.description}`.toLowerCase().includes(words),
  );
  const clearFilters = () => {
    setSearch('');
    setCategory('all');
    setGender('all');
    setOnlyFavorites(false);
  };
  const toggleFavorite = (id: string) => setFavorites(favorites.includes(id) ? favorites.filter((other) => other !== id) : [...favorites, id]);

  return (
    <PageLayout
      title="Gallery"
      description="Ready-made voices, created on your computer from a description. Listen to one, then add it to Saved voices to use it anywhere. The first listen takes a little while."
      wide
    >
      <ErrorAlert message={error} />
      {presets === null && <Skeleton className="h-40 w-full" />}
      {!!presets?.length && (
        <div className="grid items-end gap-4 sm:grid-cols-[2fr_1fr_1fr_auto]">
          <Field label="Search" htmlFor="gallery-search">
            <div className="relative">
              <Search className="text-muted-foreground pointer-events-none absolute top-2.5 left-3 size-4" />
              <Input id="gallery-search" type="search" className="pl-9" aria-label="Search voices" placeholder="Warm, deep, narrator…" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
          </Field>
          <Field label="Category" htmlFor="gallery-category">
            <ChoiceSelect id="gallery-category" options={[['all', 'All categories'], ...categories.map((c): [string, string] => [c, c])]} value={category} onChange={setCategory} />
          </Field>
          <Field label="Gender" htmlFor="gallery-gender">
            <ChoiceSelect id="gallery-gender" options={GENDERS} value={gender} onChange={setGender} />
          </Field>
          <Button variant={onlyFavorites ? 'default' : 'outline'} aria-pressed={onlyFavorites} onClick={() => setOnlyFavorites(!onlyFavorites)}>
            <Star /> Favorites
          </Button>
        </div>
      )}
      {!!presets?.length && (
        <p aria-live="polite" className="text-muted-foreground text-sm">{visible?.length} {visible?.length === 1 ? 'voice' : 'voices'}</p>
      )}
      {!!presets?.length && visible?.length === 0 && (
        <div className="flex flex-col items-center gap-3">
          <EmptyState icon={Search} title="No voices match.">Try another word, or a different category.</EmptyState>
          <Button variant="outline" onClick={clearFilters}>Clear filters</Button>
        </div>
      )}
      {categories.filter((c) => visible?.some((p) => p.category === c)).map((c) => (
        <div key={c} className="flex flex-col gap-3">
          <h2 className="text-muted-foreground text-sm font-medium tracking-wide uppercase">{c}</h2>
          <div className="grid gap-4 @2xl:grid-cols-2 @5xl:grid-cols-3 @7xl:grid-cols-4">
            {visible?.filter((p) => p.category === c).map((p) => (
              <PresetCard key={p.id} preset={p} onUpdated={replace} favorite={favorites.includes(p.id)} onFavorite={() => toggleFavorite(p.id)} />
            ))}
          </div>
        </div>
      ))}
    </PageLayout>
  );
}

function PresetCard({ preset, onUpdated, favorite, onFavorite }: { preset: Preset; onUpdated: (p: Preset) => void; favorite: boolean; onFavorite: () => void }) {
  const [busy, setBusy] = useState<'listen' | 'add' | null>(null);
  const [added, setAdded] = useState<Voice | null>(null);
  const [listened, setListened] = useState(false);
  const [error, setError] = useState('');

  async function listen() {
    setBusy('listen');
    setError('');
    try {
      onUpdated(await sendJson<Preset>(`/api/gallery/presets/${preset.id}/sample`, 'POST'));
      setListened(true);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  async function add() {
    setBusy('add');
    setError('');
    try {
      setAdded(await sendJson<Voice>(`/api/gallery/presets/${preset.id}/add`, 'POST', {}));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle>{preset.name}</CardTitle>
        <CardDescription>{preset.description}</CardDescription>
        <CardAction>
          <Button
            variant="ghost"
            size="icon"
            aria-pressed={favorite}
            aria-label={favorite ? `Remove ${preset.name} from favorites` : `Add ${preset.name} to favorites`}
            onClick={onFavorite}
          >
            <Star className={cn(favorite && 'fill-primary text-primary')} />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        {preset.audio_url ? (
          <AudioResult src={apiUrl(preset.audio_url)} autoPlay={listened} />
        ) : (
          <p className="text-muted-foreground text-sm italic">“{preset.sample}”</p>
        )}
        <ErrorAlert message={error} />
      </CardContent>
      <CardFooter className="flex-wrap gap-2">
        {!preset.ready && (
          <Button disabled={busy !== null} onClick={listen}>
            <Headphones /> {busy === 'listen' ? 'Creating the voice…' : 'Listen'}
          </Button>
        )}
        {preset.ready && !added && (
          <Button variant="outline" disabled={busy !== null} onClick={add}>
            <Plus /> {busy === 'add' ? 'Adding…' : 'Add to my voices'}
          </Button>
        )}
        {added && (
          <span className="text-success flex items-center gap-1 text-sm">
            <Check className="size-4" /> Added as “{added.name}” in Saved voices.
          </span>
        )}
      </CardFooter>
    </Card>
  );
}
