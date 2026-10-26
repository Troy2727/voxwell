import { useEffect, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { api } from '../../api';
import { ErrorAlert, Muted, Page as PageLayout, Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import PhoneCard from './PhoneCard';

interface Info {
  api_base: string;
  mcp: { command: string; args: string[]; env: Record<string, string> };
}

function Snippet({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-start gap-2">
      <pre className="bg-muted/40 min-w-0 flex-1 overflow-x-auto rounded-lg border p-3 font-mono text-xs leading-relaxed">{code}</pre>
      <Button variant="outline" size="sm" onClick={() => navigator.clipboard.writeText(code).then(() => setCopied(true))}>
        {copied ? <Check /> : <Copy />} {copied ? 'Copied' : 'Copy'}
      </Button>
    </div>
  );
}

const Label = ({ children }: { children: React.ReactNode }) => <span className="text-sm font-medium">{children}</span>;

export default function Page() {
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api<Info>('/api/integrations/info').then(setInfo, (e: Error) => setError(e.message));
  }, []);

  const description = 'Other apps on this computer can use Voxwell while it is open. Everything stays on your machine: the API only listens on this computer, so no API key is needed.';
  if (error) return <PageLayout title="Integrations" description={description}><ErrorAlert message={error} /></PageLayout>;
  if (!info) return <PageLayout title="Integrations" description={description}><Skeleton className="h-64 w-full" /></PageLayout>;

  const base = info.api_base;
  const mcpJson = JSON.stringify({ mcpServers: { voxwell: info.mcp } }, null, 2);
  const envFlags = Object.entries(info.mcp.env).map(([k, v]) => `-e ${k}=${v}`).join(' ');
  const quote = (s: string) => (/\s/.test(s) ? `"${s}"` : s);

  return (
    <PageLayout title="Integrations" description={description}>
      <Section
        title="OpenAI-compatible API"
        description={
          <>
            Works with tools and code written for OpenAI's audio API. Set the base URL to the address below; any API key is
            accepted. <code>voice</code> is a saved voice's name (OpenAI names like “alloy” use the default voice);
            <code> language</code> is an extra option (default <code>en</code>).
          </>
        }
      >
        <Snippet code={base} />
        <Label>Text to speech</Label>
        <Snippet code={`curl ${base}/audio/speech -H "Content-Type: application/json" \\
  -d '{"input": "Hello from Voxwell!", "voice": "default", "response_format": "wav"}' \\
  -o hello.wav`} />
        <Label>Transcription</Label>
        <Snippet code={`curl ${base}/audio/transcriptions -F file=@recording.mp3 -F response_format=srt`} />
        <Label>Python (openai package)</Label>
        <Snippet code={`from openai import OpenAI

client = OpenAI(base_url="${base}", api_key="local")
speech = client.audio.speech.create(model="tts-1", voice="default", input="Hello!", response_format="wav")
speech.write_to_file("hello.wav")

with open("recording.mp3", "rb") as f:
    print(client.audio.transcriptions.create(model="whisper-1", file=f).text)`} />
        <Muted className="text-xs">
          Formats: <code>wav</code> and <code>pcm</code> always work; <code>mp3</code>, <code>flac</code>, <code>opus</code>,
          <code> aac</code> and a <code>speed</code> other than 1.0 need ffmpeg. Transcripts: json, text, srt, vtt, verbose_json.
        </Muted>
      </Section>

      <Section
        title="AI assistants (MCP)"
        description={
          <>
            Lets assistants such as Claude list your voices, speak text into a WAV file and transcribe files. Keep Voxwell open
            while the assistant uses it. Requires <a href="https://docs.astral.sh/uv/">uv</a>.
          </>
        }
      >
        <Label>Claude Code</Label>
        <Snippet code={`claude mcp add voxwell ${envFlags} -- ${info.mcp.command} ${info.mcp.args.map(quote).join(' ')}`} />
        <Label>Claude Desktop and other MCP clients (JSON config)</Label>
        <Snippet code={mcpJson} />
      </Section>

      <Section
        title="n8n and other automation tools"
        description={
          <>
            In n8n, create an OpenAI credential with any API key and set its Base URL to <code>{base}</code>; the OpenAI node's
            audio actions then run on Voxwell. Tools without an OpenAI option can call the same addresses with an HTTP request
            (see the curl examples above). If n8n runs in Docker, use <code>host.docker.internal</code> instead of{' '}
            <code>127.0.0.1</code>.
          </>
        }
      />

      <PhoneCard />
    </PageLayout>
  );
}
