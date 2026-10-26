import { useEffect, useState } from 'react';
import { api } from '../../api';

interface Info {
  api_base: string;
  mcp: { command: string; args: string[]; env: Record<string, string> };
}

function Snippet({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ position: 'relative' }}>
      <pre style={{ margin: 0, padding: 12, paddingRight: 72, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflowX: 'auto', fontSize: 13 }}>
        {code}
      </pre>
      <button
        className="secondary"
        style={{ position: 'absolute', top: 6, right: 6 }}
        onClick={() => navigator.clipboard.writeText(code).then(() => setCopied(true))}
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

export default function Page() {
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api<Info>('/api/integrations/info').then(setInfo, (e: Error) => setError(e.message));
  }, []);

  if (error) return <section className="page"><h1>Integrations</h1><p className="error">{error}</p></section>;
  if (!info) return <section className="page"><h1>Integrations</h1><p className="meta">Loading…</p></section>;

  const base = info.api_base;
  const mcpJson = JSON.stringify({ mcpServers: { voxwell: info.mcp } }, null, 2);
  const envFlags = Object.entries(info.mcp.env).map(([k, v]) => `-e ${k}=${v}`).join(' ');
  const quote = (s: string) => (/\s/.test(s) ? `"${s}"` : s);

  return (
    <section className="page">
      <h1>Integrations</h1>
      <p className="meta">
        Other apps on this computer can use Voxwell while it is open. Everything stays on your machine: the API only
        listens on this computer, so no API key is needed.
      </p>

      <div className="card">
        <h2 style={{ margin: 0 }}>OpenAI-compatible API</h2>
        <p className="meta" style={{ margin: 0 }}>
          Works with tools and code written for OpenAI's audio API. Set the base URL to the address below; any API
          key is accepted. <code>voice</code> is a saved voice's name (OpenAI names like “alloy” use the default voice);
          <code> language</code> is an extra option (default <code>en</code>).
        </p>
        <Snippet code={base} />
        <strong>Text to speech</strong>
        <Snippet code={`curl ${base}/audio/speech -H "Content-Type: application/json" \\
  -d '{"input": "Hello from Voxwell!", "voice": "default", "response_format": "wav"}' \\
  -o hello.wav`} />
        <strong>Transcription</strong>
        <Snippet code={`curl ${base}/audio/transcriptions -F file=@recording.mp3 -F response_format=srt`} />
        <strong>Python (openai package)</strong>
        <Snippet code={`from openai import OpenAI

client = OpenAI(base_url="${base}", api_key="local")
speech = client.audio.speech.create(model="tts-1", voice="default", input="Hello!", response_format="wav")
speech.write_to_file("hello.wav")

with open("recording.mp3", "rb") as f:
    print(client.audio.transcriptions.create(model="whisper-1", file=f).text)`} />
        <p className="meta" style={{ margin: 0 }}>
          Formats: <code>wav</code> and <code>pcm</code> always work; <code>mp3</code>, <code>flac</code>, <code>opus</code>,
          <code> aac</code> and a <code>speed</code> other than 1.0 need ffmpeg. Transcripts: json, text, srt, vtt, verbose_json.
        </p>
      </div>

      <div className="card">
        <h2 style={{ margin: 0 }}>AI assistants (MCP)</h2>
        <p className="meta" style={{ margin: 0 }}>
          Lets assistants such as Claude list your voices, speak text into a WAV file and transcribe files. Keep Voxwell
          open while the assistant uses it. Requires <a href="https://docs.astral.sh/uv/">uv</a>.
        </p>
        <strong>Claude Code</strong>
        <Snippet code={`claude mcp add voxwell ${envFlags} -- ${info.mcp.command} ${info.mcp.args.map(quote).join(' ')}`} />
        <strong>Claude Desktop and other MCP clients (JSON config)</strong>
        <Snippet code={mcpJson} />
      </div>

      <div className="card">
        <h2 style={{ margin: 0 }}>n8n and other automation tools</h2>
        <p className="meta" style={{ margin: 0 }}>
          In n8n, create an OpenAI credential with any API key and set its Base URL to <code>{base}</code>; the OpenAI
          node's audio actions then run on Voxwell. Tools without an OpenAI option can call the same addresses with an
          HTTP request (see the curl examples above). If n8n runs in Docker, use <code>host.docker.internal</code> instead
          of <code>127.0.0.1</code>.
        </p>
      </div>
    </section>
  );
}
