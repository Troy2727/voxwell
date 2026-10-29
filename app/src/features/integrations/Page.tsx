import { useEffect, useState } from 'react';
import { Check, Copy, Download } from 'lucide-react';
import { toast } from 'sonner';
import { api, BACKEND_URL, sendJson } from '../../api';
import { message, Muted, Page as PageLayout, Section } from '@/components/page';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import PhoneCard from './PhoneCard';

type Agent = 'claude' | 'codex';

interface Info {
  api_base: string;
  cli: string;
  skill: Record<Agent, boolean>;
  mcp: { command: string; args: string[]; env: Record<string, string> };
}

/** What the page shows while the backend is unreachable: the generic commands, with <voxwell> for the install folder. */
const OFFLINE_INFO: Info = {
  api_base: `${BACKEND_URL}/v1`,
  cli: 'uv run --directory <voxwell>/backend voxwell',
  skill: { claude: false, codex: false },
  mcp: { command: 'uv', args: ['run', '--directory', '<voxwell>/backend', 'voxwell-mcp'], env: { UV_SYSTEM_CERTS: '1' } },
};

/** The nine tools, the same in the CLI and the MCP server (backend/voxwell/cli.py, mcp_server.py). */
const TOOLS: { cli: string; mcp: string; what: string }[] = [
  { cli: 'voices', mcp: 'list_voices', what: 'List saved voices' },
  { cli: 'collection', mcp: 'voice_collections', what: 'Organize saved voices into collections' },
  { cli: 'speak', mcp: 'speak', what: 'Turn text into speech (WAV)' },
  { cli: 'transcribe', mcp: 'transcribe', what: 'Transcribe an audio or video file' },
  { cli: 'isolate', mcp: 'isolate_voice', what: 'Split a recording into the voice and the background' },
  { cli: 'clone', mcp: 'clone_voice', what: 'Save a voice from a short, clean recording' },
  { cli: 'design', mcp: 'design_voice', what: 'Create a voice from a description' },
  { cli: 'convert', mcp: 'convert_voice', what: 'Re-speak a recording in a saved voice' },
  { cli: 'dub', mcp: 'dub_video', what: 'Dub a video into another language (MP4 + SRT)' },
];

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

const AGENTS: { id: Agent; name: string; folder: string }[] = [
  { id: 'claude', name: 'Claude Code', folder: '~/.claude/skills/voxwell' },
  { id: 'codex', name: 'Codex', folder: '~/.codex/skills/voxwell' },
];

/** Installs the Voxwell skill (how to use the CLI) where Claude Code or Codex looks for skills. */
function SkillButtons({ installed, offline, onInstalled }: { installed: Record<Agent, boolean>; offline: boolean; onInstalled: (agent: Agent) => void }) {
  const [busy, setBusy] = useState<Agent | null>(null);

  async function install(agent: Agent, name: string) {
    setBusy(agent);
    try {
      const { path } = await sendJson<{ path: string }>(`/api/integrations/skill/${agent}`, 'POST');
      onInstalled(agent);
      toast.success(`Installed for ${name}`, { description: path });
    } catch (e) {
      toast.error(`Could not install for ${name}`, { description: message(e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      {AGENTS.map((a) => (
        <Button key={a.id} variant={installed[a.id] ? 'outline' : 'default'} disabled={offline || busy !== null} onClick={() => install(a.id, a.name)} title={a.folder}>
          {installed[a.id] ? <Check /> : <Download />}
          {busy === a.id ? 'Installing…' : installed[a.id] ? `Installed for ${a.name} (update)` : `Install for ${a.name}`}
        </Button>
      ))}
    </div>
  );
}

export default function Page() {
  const [loaded, setLoaded] = useState<Info | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    api<Info>('/api/integrations/info').then(setLoaded, () => setOffline(true));
  }, []);

  const description = 'Other apps on this computer can use Voxwell while it is open. Everything stays on your machine: the API only listens on this computer, so no API key is needed.';
  if (!loaded && !offline) return <PageLayout title="Integrations" description={description}><Skeleton className="h-64 w-full" /></PageLayout>;

  const info = loaded ?? OFFLINE_INFO;
  const base = info.api_base;
  const mcpJson = JSON.stringify({ mcpServers: { voxwell: info.mcp } }, null, 2);
  const envFlags = Object.entries(info.mcp.env).map(([k, v]) => `-e ${k}=${v}`).join(' ');
  const quote = (s: string) => (/\s/.test(s) ? `"${s}"` : s);

  return (
    <PageLayout title="Integrations" description={description}>
      {offline && (
        <Alert>
          <AlertDescription>
            <p>
              Voxwell's backend isn't running, so the commands below show <code>&lt;voxwell&gt;</code> where your Voxwell folder
              goes. Open the Voxwell app to fill in this computer's commands and install the agent skill.
            </p>
          </AlertDescription>
        </Alert>
      )}

      <Section title="Eight tools, two ways in" description="The command line and MCP share the same eight tools.">
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left">
              <tr>
                <th className="px-3 py-2 font-medium">Command line</th>
                <th className="px-3 py-2 font-medium">MCP tool</th>
                <th className="px-3 py-2 font-medium">What it does</th>
              </tr>
            </thead>
            <tbody>
              {TOOLS.map((t) => (
                <tr key={t.mcp} className="border-t">
                  <td className="px-3 py-2 font-mono text-xs">voxwell {t.cli}</td>
                  <td className="px-3 py-2 font-mono text-xs">{t.mcp}</td>
                  <td className="text-muted-foreground px-3 py-2">{t.what}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

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
        title="Command line (Claude Code, Codex, scripts)"
        description={
          <>
            The <code>voxwell</code> command speaks, transcribes, isolates voices, clones and designs voices, converts and dubs,
            from a terminal or an AI coding agent. Add <code>--json</code> for machine-readable output. Keep Voxwell open while
            it runs.
          </>
        }
      >
        <Label>Command on this computer</Label>
        <Snippet code={`${info.cli} --help
${info.cli} speak "Hello from Voxwell" -o hello.wav
${info.cli} isolate song.mp3`} />
        <Label>Teach your AI agent</Label>
        <Muted>
          Installs a skill that tells the agent when and how to use Voxwell, with the command above filled in. Then just ask,
          e.g. “isolate the voice in song.mp3”.
        </Muted>
        <SkillButtons installed={info.skill} offline={offline} onInstalled={(agent) => setLoaded({ ...info, skill: { ...info.skill, [agent]: true } })} />
      </Section>

      <Section
        title="AI assistants (MCP)"
        description={
          <>
            Gives AI apps without a terminal, such as Claude Desktop and Cursor, the same eight tools as the command line: speak, transcribe, isolate, clone, design, convert, dub and list voices. Keep Voxwell open
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
