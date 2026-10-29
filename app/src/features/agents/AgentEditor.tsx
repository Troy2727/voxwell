import { useState } from 'react';
import { Save, Trash2 } from 'lucide-react';
import { sendJson, type Voice } from '@/api';
import { ChoiceSelect } from '@/components/choice-select';
import { ConfirmButton } from '@/components/confirm-button';
import { ErrorAlert, Field, message, Section } from '@/components/page';
import { VoiceSelect } from '@/components/voice-select';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { Agent, AgentStatus } from './types';

const names = new Intl.DisplayNames(['en'], { type: 'language' });

/** Create or edit a saved agent. `agent` null means a new one. */
export default function AgentEditor({ agent, status, voices, onSaved, onDeleted, onCancel }: {
  agent: Agent | null;
  status: AgentStatus;
  voices: Voice[] | null;
  onSaved: (agent: Agent) => void;
  onDeleted: (id: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(agent?.name ?? '');
  const [prompt, setPrompt] = useState(agent?.system_prompt ?? 'You are a friendly assistant. Keep answers short.');
  const [voice, setVoice] = useState(agent?.voice ?? '');
  const [language, setLanguage] = useState(agent?.language ?? 'en');
  const [tools, setTools] = useState<string[]>(agent?.tools ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const languages = status.languages
    .map((c) => [c, names.of(c) ?? c] as [string, string])
    .sort((a, b) => a[1].localeCompare(b[1]));

  const save = async () => {
    setBusy(true);
    setError('');
    try {
      const body = { name, system_prompt: prompt, voice, language, tools };
      const saved = agent
        ? await sendJson<Agent>(`/api/agents/agents/${agent.id}`, 'PUT', body)
        : await sendJson<Agent>('/api/agents/agents', 'POST', body);
      onSaved(saved);
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!agent) return;
    setBusy(true);
    try {
      await sendJson(`/api/agents/agents/${agent.id}`, 'DELETE');
      onDeleted(agent.id);
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  };

  return (
    <Section title={agent ? `Edit ${agent.name}` : 'New agent'}>
      <Field label="Name" htmlFor="agent-name">
        <Input id="agent-name" value={name} maxLength={80} disabled={busy} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Instructions" htmlFor="agent-prompt" hint="Who the agent is and how it should answer. Replies are spoken, so short is better.">
        <Textarea id="agent-prompt" rows={4} maxLength={4000} value={prompt} disabled={busy} onChange={(e) => setPrompt(e.target.value)} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Voice">
          <VoiceSelect voices={voices} value={voice} onChange={setVoice} disabled={busy} />
        </Field>
        <Field label="Language" hint="What it listens for and speaks.">
          <ChoiceSelect options={languages} value={language} disabled={busy} onChange={setLanguage} />
        </Field>
      </div>
      <Field label="Tools" hint="Read-only helpers the agent may use. It cannot run anything else.">
        <div className="flex flex-col gap-2">
          {status.tools.map((t) => (
            <label key={t.name} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={tools.includes(t.name)}
                disabled={busy}
                onCheckedChange={(on) => setTools((list) => (on ? [...list, t.name] : list.filter((x) => x !== t.name)))}
              />
              <span className="font-medium">{t.name.replace('_', ' ')}</span>
              <span className="text-muted-foreground">{t.description}</span>
            </label>
          ))}
        </div>
      </Field>
      <div role="alert">
        <ErrorAlert message={error} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={save} disabled={busy || !name.trim()}>
          <Save /> Save
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        {agent && (
          <div className="ml-auto">
            <ConfirmButton title={`Delete ${agent.name}?`} onConfirm={remove} disabled={busy}>
              <Trash2 /> Delete
            </ConfirmButton>
          </div>
        )}
      </div>
    </Section>
  );
}
