import { useEffect, useRef, useState } from 'react';
import { Bot, Mic, Radio, Send, Square, Trash2, Wrench } from 'lucide-react';
import { sendJson } from '@/api';
import { EmptyState, ErrorAlert, Field, message, Muted, Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MicSelector } from '@/components/ui/mic-selector';
import { type LiveMessage, useLiveAudio } from '@/hooks/use-live-audio';
import { cn } from '@/lib/utils';
import type { Agent, ToolCall } from './types';

interface Message {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: ToolCall[];
  warning?: string;
  failed?: boolean; // an error shown in the conversation, never sent back as history
}

interface Reply {
  reply: string;
  tool_calls: ToolCall[];
  audio?: string;
  warning?: string;
}

const HISTORY = 12; // messages sent back with each turn (the server uses at most this many)

function ToolCalls({ calls }: { calls: ToolCall[] }) {
  return (
    <div className="flex flex-col gap-1">
      {calls.map((c, i) => (
        <p key={i} className="text-muted-foreground flex items-start gap-1.5 text-xs">
          <Wrench className="mt-0.5 size-3 shrink-0" />
          <span className="break-all">
            <span className="font-medium">{c.tool || 'tool call'}</span>
            {c.tool && `(${JSON.stringify(c.arguments ?? {})})`} → {c.error ? <span className="text-destructive">{c.error}</span> : c.result}
          </span>
        </p>
      ))}
    </div>
  );
}

/** Talk to one agent: type, hold to talk, or a hands-free live conversation. */
export default function Conversation({ agent }: { agent: Agent }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState(0);
  const [error, setError] = useState('');
  const [warning, setWarning] = useState('');
  const [device, setDevice] = useState('');
  const [muted, setMuted] = useState(false);
  const [mode, setMode] = useState<'hold' | 'live' | null>(null);
  const [playing, setPlaying] = useState(false);
  const nextId = useRef(0);
  const queue = useRef<string[]>([]);
  const audio = useRef<HTMLAudioElement | null>(null);
  const held = useRef(false);
  const bottom = useRef<HTMLDivElement>(null);

  const history = () => messages.filter((m) => !m.failed).slice(-HISTORY).map(({ role, content }) => ({ role, content }));
  const add = (...items: Omit<Message, 'id'>[]) => setMessages((list) => [...list, ...items.map((m) => ({ ...m, id: nextId.current++ }))]);

  // Replies play in order; the microphone sends silence meanwhile, so the agent does not hear itself.
  const playNext = () => {
    const src = queue.current.shift();
    if (!src) {
      audio.current = null;
      setPlaying(false);
      live.pause(false);
      return;
    }
    const el = new Audio(src);
    audio.current = el;
    setPlaying(true);
    live.pause(true);
    el.onended = el.onerror = () => playNext();
    el.play().catch(() => playNext());
  };
  const play = (base64: string | undefined) => {
    if (!base64) return;
    queue.current.push(`data:audio/wav;base64,${base64}`);
    if (!audio.current) playNext();
  };
  const stopPlayback = () => {
    queue.current = [];
    audio.current?.pause();
    audio.current = null;
    setPlaying(false);
    live.pause(false);
  };

  const onMessage = (m: LiveMessage) => {
    if (m.type === 'turn_end' && m.index != null) setPending((p) => p + 1);
    else if (m.type === 'warning') setWarning(m.message ?? '');
    else if (m.type === 'error' && m.index != null) {
      setPending((p) => Math.max(0, p - 1));
      add({ role: 'assistant', content: m.message ?? 'That turn failed.', failed: true });
    } else if (m.type === 'turn') {
      setPending((p) => Math.max(0, p - 1));
      const transcript = typeof m.transcript === 'string' ? m.transcript : '';
      if (!transcript) return;
      const r = m as unknown as Reply;
      add({ role: 'user', content: transcript }, { role: 'assistant', content: r.reply, toolCalls: r.tool_calls, warning: r.warning });
      play(r.audio);
    }
  };
  const live = useLiveAudio(`/api/agents/agents/${agent.id}/live`, onMessage);
  const active = live.status !== 'idle';

  useEffect(() => {
    if (!active) {
      setPending(0);
      setMode(null);
    }
  }, [active]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'nearest' }); // newer Chromium returns a promise: not a cleanup
  }, [messages.length]);
  useEffect(() => () => stopPlayback(), []);

  const sendText = async () => {
    const message_ = text.trim();
    if (!message_) return;
    setSending(true);
    setError('');
    try {
      const r = await sendJson<Reply>(`/api/agents/agents/${agent.id}/chat`, 'POST', { message: message_, history: history(), speak: true });
      setText('');
      add({ role: 'user', content: message_ }, { role: 'assistant', content: r.reply, toolCalls: r.tool_calls, warning: r.warning });
      play(r.audio);
    } catch (e) {
      setError(message(e));
    } finally {
      setSending(false);
    }
  };

  const startLive = () => {
    setWarning('');
    setMode('live');
    void live.start({ history: history() }, device || undefined);
  };
  // Hold to talk: one session per press. A long trailing-silence window keeps a pause inside one turn;
  // letting go ends the session, which answers the last turn.
  const pressTalk = async () => {
    held.current = true;
    setWarning('');
    stopPlayback();
    setMode('hold');
    await live.start({ history: history(), silence_ms: 3000, max_turn_s: 30 }, device || undefined);
    if (!held.current) live.stop();
  };
  const releaseTalk = () => {
    if (!held.current) return;
    held.current = false;
    live.stop();
  };

  const state =
    live.status === 'connecting' ? 'Connecting…'
      : playing ? 'Speaking…'
        : live.status === 'finishing' || pending || sending ? 'Thinking…'
          : live.status !== 'listening' ? ''
            : live.speaking ? '● Hearing you…'
              : mode === 'hold' ? 'Listening while you hold…'
                : 'Listening…';

  return (
    <Section
      title={`Talk to ${agent.name}`}
      action={
        messages.length > 0 && (
          <Button variant="ghost" size="sm" onClick={() => setMessages([])} disabled={active || sending}>
            <Trash2 /> Clear
          </Button>
        )
      }
    >
      <div className="flex max-h-[28rem] min-h-40 flex-col gap-3 overflow-y-auto rounded-xl border p-4">
        {messages.length === 0 ? (
          <EmptyState icon={Bot} title="No conversation yet">
            Type a message, hold the talk button, or start a live conversation.
          </EmptyState>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={cn('flex max-w-[85%] flex-col gap-1', m.role === 'user' ? 'self-end items-end' : 'self-start')}>
              <p
                className={cn(
                  'rounded-2xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap',
                  m.failed ? 'text-destructive border' : m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted',
                )}
              >
                {m.content}
              </p>
              {m.toolCalls && m.toolCalls.length > 0 && <ToolCalls calls={m.toolCalls} />}
              {m.warning && <Muted className="text-xs">{m.warning}</Muted>}
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void sendText();
        }}
      >
        <Input value={text} placeholder={`Message ${agent.name}`} maxLength={2000} disabled={sending || active} onChange={(e) => setText(e.target.value)} />
        <Button type="submit" disabled={sending || active || !text.trim()}>
          <Send /> Send
        </Button>
      </form>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant={mode === 'hold' ? 'destructive' : 'outline'}
          disabled={sending || muted || mode === 'live' || live.status === 'finishing'}
          onPointerDown={() => void pressTalk()}
          onPointerUp={releaseTalk}
          onPointerLeave={releaseTalk}
          onKeyDown={(e) => {
            if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) void pressTalk();
          }}
          onKeyUp={(e) => {
            if (e.key === ' ' || e.key === 'Enter') releaseTalk();
          }}
        >
          <Mic /> Hold to talk
        </Button>
        <Button
          variant={mode === 'live' ? 'destructive' : 'default'}
          disabled={sending || mode === 'hold' || live.status === 'finishing' || (!active && muted)}
          onClick={mode === 'live' ? live.stop : startLive}
        >
          {mode === 'live' ? <Square /> : <Radio />} {mode === 'live' ? 'End conversation' : 'Live conversation'}
        </Button>
        {state && (
          <span aria-live="polite" className={live.speaking ? 'text-destructive text-sm' : 'text-muted-foreground text-sm'}>
            {state}
          </span>
        )}
      </div>
      <Field label="Microphone" hint={muted ? 'Muted: unmute it to talk.' : 'The microphone pauses while the agent speaks.'}>
        <MicSelector value={device} onValueChange={setDevice} muted={muted} onMutedChange={setMuted} disabled={active} className="w-full justify-start border sm:w-full" />
      </Field>
      {warning && <Muted className="text-xs">{warning}</Muted>}
      <div role="alert">
        <ErrorAlert message={error || live.error} />
      </div>
    </Section>
  );
}
