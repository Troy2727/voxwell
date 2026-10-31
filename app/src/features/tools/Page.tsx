import { useEffect, useState } from 'react';
import { listVoices, type Voice } from '../../api';
import { Page as PageLayout } from '@/components/page';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Compare } from './Compare';
import { Convert } from './Convert';
import { Direct } from './Direct';
import { Fit } from './Fit';
import { Isolate } from './Isolate';
import { Probe } from './Probe';

const TOOLS = [
  { id: 'convert', title: 'Convert voice', hint: 'Re-speak a recording in one of your saved voices. The words and timing stay the same.' },
  { id: 'isolate', title: 'Isolate voice', hint: 'Split a recording into the voice alone and everything else: music, noise and effects.' },
  { id: 'direct', title: 'AI direction', hint: 'Say how a line should sound, in your own words. A local AI turns it into settings you can adjust.' },
  { id: 'compare', title: 'Compare voices', hint: 'Hear the same sentence in several voices, side by side.' },
  { id: 'fit', title: 'Fit length', hint: 'Speed audio up or slow it down to an exact length, without changing the pitch.' },
  { id: 'probe', title: 'File info', hint: 'See the format, length and streams of an audio or video file.' },
] as const;

type ToolId = (typeof TOOLS)[number]['id'];

export default function Page() {
  const [tool, setTool] = useState<ToolId>('convert');
  const [voices, setVoices] = useState<Voice[]>([]);
  useEffect(() => {
    listVoices().then(setVoices, () => setVoices([]));
  }, []);

  return (
    <PageLayout title="Tools" description="Small jobs for audio you already have.">
      <Tabs value={tool} onValueChange={(v) => setTool(v as ToolId)}>
        {/* Wraps onto more rows on a phone; the list's own height must follow, and so must the tabs'. */}
        <TabsList className="flex-wrap group-data-[orientation=horizontal]/tabs:h-auto">
          {TOOLS.map((t) => (
            <TabsTrigger key={t.id} value={t.id} className="h-8 flex-none">{t.title}</TabsTrigger>
          ))}
        </TabsList>
        {TOOLS.map((t) => (
          <TabsContent key={t.id} value={t.id}>
            <Card>
              <CardHeader>
                <CardTitle>{t.title}</CardTitle>
                <CardDescription>{t.hint}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {t.id === 'convert' && <Convert voices={voices} />}
                {t.id === 'isolate' && <Isolate />}
                {t.id === 'direct' && <Direct voices={voices} />}
                {t.id === 'compare' && <Compare voices={voices} />}
                {t.id === 'fit' && <Fit />}
                {t.id === 'probe' && <Probe />}
              </CardContent>
            </Card>
          </TabsContent>
        ))}
      </Tabs>
    </PageLayout>
  );
}
