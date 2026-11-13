import { Fragment, useEffect, useRef, useState } from 'react';
import { Bot, ChevronRight, Mic, Radio, Send, Square, Trash2, Wrench } from 'lucide-react';
import { sendJson } from '@/api';
import { EmptyState, ErrorAlert, Field, message, Muted, Section } from '@/components/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { MicSelector } from '@/components/ui/mic-selector';
import { type LiveMessage, useLiveAudio } from '@/hooks/use-live-audio';
import { usePersisted } from '@/lib/persisted';
import { cn } from '@/lib/utils';
import { CutInDetector } from './cutIn';
import { StreamPlayer } from './streamPlayer';
import type { Agent, ToolCall } from './types';

interface Message {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: ToolCall[];
  warning?: string;
  failed?: boolean; // an error shown in the conversation, never sent back as history
  language?: string; // the language an assistant reply was given in
  turn?: string; // the live session and turn a streamed reply belongs to (turn numbers restart per session)
  interrupted?: boolean; // the user spoke over it; the text is what they heard
  mood?: string; // Mood match: how the reply was said
}

interface Reply {
  reply: string;
  tool_calls: ToolCall[];
  audio?: string;
  warning?: string;
  language: string;
  mood?: string;
}

const languageNames = new Intl.DisplayNames(['en'], { type: 'language' });

const HISTORY = 12; // messages sent back with each turn (the server uses at most this many)

/* Tool chips and the streamed reply are adapted from Beautiful UI's ToolChips and StreamingText
 * (https://github.com/slev12397/beautiful-ui), MIT License, Copyright (c) 2026 Shane Levine. */

/** One tool call as a compact row of chips; it expands to show the arguments and the result. */
function ToolChip({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const args = call.arguments && typeof call.arguments === 'object' ? Object.values(call.arguments as Record<string, unknown>) : [];
  return (
    <div className="text-xs">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="hover:bg-muted group flex max-w-full flex-wrap items-center gap-1.5 rounded-md px-1.5 py-1 text-left"
      >
        <Wrench className="text-muted-foreground size-3 shrink-0" aria-hidden />
        <span className="text-muted-foreground">Called</span>
        <span className={cn('rounded border px-1.5 font-mono', call.error ? 'text-destructive' : 'text-primary')}>{call.tool || 'tool call'}</span>
        {args.map((a, i) => (
          <span key={i} className="bg-muted max-w-48 truncate rounded border px-1.5 font-mono">{String(a)}</span>
        ))}
        <ChevronRight className={cn('text-muted-foreground size-3 opacity-0 transition group-hover:opacity-100', open && 'rotate-90 opacity-100')} aria-hidden />
      </button>
      {open && (
        <pre className="bg-muted mt-1 ml-5 overflow-x-auto rounded-md px-2.5 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all">
          {`arguments  ${JSON.stringify(call.arguments ?? {})}\n`}
          {call.error ? <span className="text-destructive">{`error      ${call.error}`}</span> : `result     ${call.result ?? ''}`}
        </pre>
      )}
    </div>
  );
}

/** A reply whose words resolve out of a blur as they arrive. The whole text is in the page at once
 *  (screen readers read it normally); when it grows, as in a live turn, only the new words animate. */
function StreamText({ text }: { text: string }) {
  // Each word's delay is fixed when it first appears, so a re-render never restarts its animation.
  const delays = useRef<number[]>([]);
  const words = text.split(/(\s+)/);
  const firstNew = delays.current.length;
  words.forEach((_, i) => {
    delays.current[i] ??= (i - firstNew) * 18;
  });
  return words.map((w, i) =>
    !w.trim() ? (
      <Fragment key={i}>{w}</Fragment>
    ) : (
      <span key={i} className="animate-in fade-in blur-in-sm fill-mode-both duration-500" style={{ animationDelay: `${delays.current[i]}ms` }}>
        {w}
      </span>
    ),
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
  const left = useRef(false); // this conversation is gone (another agent, the editor, another page)
  const bottom = useRef<HTMLDivElement>(null);
  // Flow replies (live mode): the reply being streamed, and whether its final "turn" has arrived.
  const streaming = useRef<{ turn: string; index: number; done: boolean } | null>(null);
  const session = useRef(0); // counts live sessions, so their turn numbers don't collide
  const turnKey = (index: unknown) => `${session.current}:${String(index)}`;
  const turnEndAt = useRef(0);
  const player = useRef<StreamPlayer | null>(null);
  // Cut-in: speaking over a streamed reply stops it; later messages for a cut turn are ignored.
  const detector = useRef(new CutInDetector());
  // Some setups (loud speakers, no echo cancellation) cut in on the agent's own voice: it can be turned off.
  const [cutInOn, setCutInOn] = usePersisted('voxwell.agents.cutIn', true, (saved) => saved !== false);
  const cutTurns = useRef(new Set<string>());
  const unfinishedCuts = useRef(new Set<string>()); // cut before their final message arrived

  // The language of the last reply, so a new session (each push-to-talk press) carries on in it.
  // An edit may have removed it from the agent's languages since.
  const last = [...messages].reverse().find((m) => m.language)?.language;
  // An older backend (the website can talk to one) sends agents without follow_languages.
  const follows = agent.follow_languages ?? [];
  const lastLanguage = last && [agent.language, ...follows].includes(last) ? last : agent.language;
  const history = () => messages.filter((m) => !m.failed && m.content).slice(-HISTORY).map(({ role, content }) => ({ role, content }));
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
    // A reply that lands after the user left is not spoken over whatever they opened next.
    if (!base64 || left.current) return;
    queue.current.push(`data:audio/wav;base64,${base64}`);
    if (!audio.current) playNext();
  };
  // The microphone stays silenced from the first sentence until the reply is complete and has all
  // played, including the gaps while the next sentence is still being written.
  const streamIdle = () => {
    detector.current.reset(); // a run must not carry over into the next reply
    if (streaming.current && !streaming.current.done) return;
    streaming.current = null;
    setPlaying(false);
    live.pause(false);
  };
  const streamPlayer = () =>
    (player.current ??= new StreamPlayer(
      (seq) => {
        // Echo cancellation needs a moment when the agent starts talking from silence; within a reply
        // the short gaps between sentences don't reset it, so speech over them keeps counting.
        if (seq === 0) detector.current.grace(performance.now());
        setPlaying(true);
        if (seq === 0 && import.meta.env.DEV) console.debug(`Flow replies: first audio ${Math.round(performance.now() - turnEndAt.current)} ms after turn_end`);
      },
      () => streamIdle(),
    ));
  // The user spoke over the reply: stop it at once, tell the server what was heard, and listen,
  // starting with the audio from just before, so the first words are not lost.
  const cutIn = (turn: string, index: number) => {
    const heard = player.current?.heard() ?? { seq: null, ms: 0 };
    player.current?.clear();
    cutTurns.current.add(turn);
    if (streaming.current && !streaming.current.done) {
      unfinishedCuts.current.add(turn); // its final message is still to come: stop waiting for it now
      setPending((p) => Math.max(0, p - 1));
    }
    streaming.current = null;
    detector.current.reset();
    setPlaying(false);
    setMessages((list) => list.map((x) => (x.turn === turn ? { ...x, interrupted: true } : x)));
    live.send({ type: 'cut', index, heard_seq: heard.seq, heard_ms: heard.ms });
    live.resume(true);
  };
  const stopPlayback = () => {
    player.current?.clear();
    streaming.current = null;
    queue.current = [];
    audio.current?.pause();
    audio.current = null;
    setPlaying(false);
    live.pause(false);
  };

  const onMessage = (m: LiveMessage) => {
    if (m.type === 'turn_end' && m.index != null) {
      turnEndAt.current = performance.now();
      setPending((p) => p + 1);
    } else if (m.type === 'reply_start') {
      const turn = turnKey(m.index);
      add({ role: 'user', content: String(m.transcript ?? '') }, { role: 'assistant', content: '', toolCalls: m.tool_calls as ToolCall[], turn });
      streaming.current = { turn, index: Number(m.index), done: false };
      streamPlayer().newReply();
      detector.current.reset();
    } else if (m.type === 'reply_text' && !cutTurns.current.has(turnKey(m.index))) {
      const turn = turnKey(m.index);
      setMessages((list) => list.map((x) => (x.turn === turn ? { ...x, content: x.content ? `${x.content} ${m.text}` : String(m.text) } : x)));
    } else if (m.type === 'reply_audio' && streaming.current?.turn === turnKey(m.index) && !left.current) {
      live.pause(true);
      void streamPlayer().enqueue(Number(m.seq), typeof m.audio === 'string' ? m.audio : null);
    } else if (m.type === 'turn' && m.streamed) {
      if (!unfinishedCuts.current.delete(turnKey(m.index))) setPending((p) => Math.max(0, p - 1));
      const r = m as unknown as Reply;
      const turn = turnKey(m.index);
      // A turn cut before it ended reports the heard text; one cut after it ended gets a cut_ack instead.
      const cut = cutTurns.current.has(turn);
      const content = (x: Message) => (cut && !m.cut ? x.content : r.reply);
      // The final turn also carries tool calls made after the first sentence was spoken.
      setMessages((list) => list.map((x) => (x.turn === turn ? { ...x, content: content(x), toolCalls: r.tool_calls, warning: r.warning, language: r.language, mood: r.mood } : x)));
      const current = streaming.current;
      if (current && current.turn === turn) {
        current.done = true;
        if (!player.current?.playing) streamIdle();
      }
    } else if (m.type === 'cut_ack') {
      setMessages((list) => list.map((x) => (x.turn === turnKey(m.index) && x.role === 'assistant' ? { ...x, content: String(m.reply ?? ''), interrupted: true } : x)));
    } else if (m.type === 'warning') setWarning(m.message ?? '');
    else if (m.type === 'error' && m.index != null) {
      if (!unfinishedCuts.current.delete(turnKey(m.index))) setPending((p) => Math.max(0, p - 1));
      const current = streaming.current;
      if (current && current.turn === turnKey(m.index)) {
        current.done = true; // a turn that failed after it started streaming is over
        if (!player.current?.playing) streamIdle();
      }
      add({ role: 'assistant', content: m.message ?? 'That turn failed.', failed: true });
    } else if (m.type === 'turn') {
      setPending((p) => Math.max(0, p - 1));
      const transcript = typeof m.transcript === 'string' ? m.transcript : '';
      if (!transcript) return;
      const r = m as unknown as Reply;
      add({ role: 'user', content: transcript }, { role: 'assistant', content: r.reply, toolCalls: r.tool_calls, warning: r.warning, language: r.language, mood: r.mood });
      play(r.audio);
    }
  };
  const live = useLiveAudio(`/api/agents/agents/${agent.id}/live`, onMessage);
  const active = live.status !== 'idle';
  // While a streamed reply plays, the microphone level decides whether the user is cutting in.
  useEffect(() => {
    live.watchLevel((rms, now, ms) => {
      const current = streaming.current;
      if (cutInOn && current && player.current?.playing && detector.current.feed(rms, now, ms)) cutIn(current.turn, current.index);
    });
    return () => live.watchLevel(null);
  });

  useEffect(() => {
    if (!active) {
      setPending(0);
      setMode(null);
    }
  }, [active]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'nearest' }); // newer Chromium returns a promise: not a cleanup
  }, [messages.length]);
  useEffect(() => {
    left.current = false; // StrictMode mounts twice
    return () => {
      left.current = true;
      stopPlayback();
      player.current?.close();
    };
  }, []);

  const sendText = async () => {
    const message_ = text.trim();
    if (!message_) return;
    setSending(true);
    setError('');
    try {
      const r = await sendJson<Reply>(`/api/agents/agents/${agent.id}/chat`, 'POST', { message: message_, history: history(), speak: true, language: lastLanguage });
      setText('');
      add({ role: 'user', content: message_ }, { role: 'assistant', content: r.reply, toolCalls: r.tool_calls, warning: r.warning, language: r.language, mood: r.mood });
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
    session.current++;
    cutTurns.current.clear(); // keys are per session: the last session's can go
    unfinishedCuts.current.clear();
    void live.start({ history: history(), language: lastLanguage, stream_reply: true }, device || undefined);
  };
  // Hold to talk: one session per press. A long trailing-silence window keeps a pause inside one turn;
  // letting go ends the session, which answers the last turn.
  const pressTalk = async () => {
    held.current = true;
    setWarning('');
    stopPlayback();
    setMode('hold');
    await live.start({ history: history(), language: lastLanguage, silence_ms: 3000, max_turn_s: 30 }, device || undefined);
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
          messages.map((m, i) => (
            <div key={m.id} className={cn('flex max-w-[85%] flex-col gap-1', m.role === 'user' ? 'self-end items-end' : 'self-start')}>
              <p
                className={cn(
                  'rounded-2xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap',
                  m.failed ? 'text-destructive border' : m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted',
                )}
              >
                {m.role === 'assistant' && !m.failed ? <StreamText text={m.content} /> : m.content}
              </p>
              {m.language && follows.length > 0 && (
                <Muted className={cn('text-xs', m.language !== (messages.slice(0, i).reverse().find((x) => x.language)?.language ?? agent.language) && 'text-primary font-medium')}>
                  {languageNames.of(m.language) ?? m.language}
                </Muted>
              )}
              {m.interrupted && <Muted className="text-xs">Interrupted</Muted>}
              {m.mood && (
                <Badge variant="secondary" className="text-xs capitalize" aria-label={`Mood: ${m.mood}`}>
                  {m.mood}
                </Badge>
              )}
              {m.toolCalls && m.toolCalls.length > 0 && (
                <div className="flex flex-col">
                  {m.toolCalls.map((c, j) => <ToolChip key={j} call={c} />)}
                </div>
              )}
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
      <Field label="Microphone" hint={muted ? 'Muted: unmute it to talk.' : cutInOn ? 'In a live conversation, start talking to interrupt the agent.' : 'The microphone pauses while the agent speaks.'}>
        <MicSelector value={device} onValueChange={setDevice} muted={muted} onMutedChange={setMuted} disabled={active} className="w-full justify-start border sm:w-full" />
      </Field>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={cutInOn} onCheckedChange={(on) => setCutInOn(on === true)} aria-label="Talk over the agent to interrupt it" />
        Talk over the agent to interrupt it
      </label>
      {warning && <Muted className="text-xs">{warning}</Muted>}
      <div role="alert">
        <ErrorAlert message={error || live.error} />
      </div>
    </Section>
  );
}
