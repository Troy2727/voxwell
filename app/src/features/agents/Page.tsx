import { useEffect, useState } from 'react';
import { Bot, Pencil, Plus } from 'lucide-react';
import { api, listVoices, type Voice } from '@/api';
import { EmptyState, ErrorAlert, message, Page as PageLayout, Section } from '@/components/page';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import AgentEditor from './AgentEditor';
import Conversation from './Conversation';
import type { Agent, AgentStatus } from './types';

export default function Page() {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState<'new' | string | null>(null);

  useEffect(() => {
    Promise.all([api<AgentStatus>('/api/agents/status'), api<Agent[]>('/api/agents/agents')])
      .then(([s, list]) => {
        setStatus(s);
        setAgents(list);
        setSelected(list[0]?.id ?? null);
      })
      .catch((e) => setLoadError(message(e)));
    listVoices().then(setVoices).catch(() => setVoices([]));
  }, []);

  const current = agents?.find((a) => a.id === selected) ?? null;
  const saved = (agent: Agent) => {
    setAgents((list) => [...(list ?? []).filter((a) => a.id !== agent.id), agent].sort((a, b) => a.name.localeCompare(b.name)));
    setSelected(agent.id);
    setEditing(null);
  };
  const deleted = (id: string) => {
    const rest = (agents ?? []).filter((a) => a.id !== id);
    setAgents(rest);
    setSelected(rest[0]?.id ?? null);
    setEditing(null);
  };

  return (
    <PageLayout
      title="Voice agents"
      description="Talk with a local AI model that answers in a saved voice and can use a few safe tools."
      actions={
        status && (
          <Button onClick={() => setEditing('new')} disabled={editing !== null}>
            <Plus /> New agent
          </Button>
        )
      }
    >
      {loadError && <ErrorAlert message={`Could not load the agents: ${loadError}`} />}
      {!loadError && (!status || !agents) && <Skeleton className="h-40 w-full" />}
      {status && agents && (
        <>
          <Section title="Agents">
            {agents.length === 0 ? (
              <EmptyState icon={Bot} title="No agents yet">
                Create one: give it a name, instructions, a voice and the tools it may use.
              </EmptyState>
            ) : (
              <div className="flex flex-wrap gap-2">
                {agents.map((a) => (
                  <div key={a.id} className={cn('flex items-center rounded-lg border', a.id === selected && 'border-primary bg-muted/50')}>
                    <Button variant="ghost" size="sm" onClick={() => setSelected(a.id)} disabled={editing !== null}>
                      <Bot /> {a.name}
                    </Button>
                    <Button variant="ghost" size="icon" className="size-8" aria-label={`Edit ${a.name}`} onClick={() => setEditing(a.id)} disabled={editing !== null}>
                      <Pencil />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </Section>
          {editing !== null ? (
            <AgentEditor
              key={editing}
              agent={editing === 'new' ? null : (agents.find((a) => a.id === editing) ?? null)}
              status={status}
              voices={voices}
              onSaved={saved}
              onDeleted={deleted}
              onCancel={() => setEditing(null)}
            />
          ) : (
            current && <Conversation key={current.id} agent={current} />
          )}
        </>
      )}
    </PageLayout>
  );
}
