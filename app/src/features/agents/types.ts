export interface Agent {
  id: string;
  name: string;
  system_prompt: string;
  voice: string;
  language: string;
  tools: string[];
  follow_languages: string[];
}

export interface AgentStatus {
  ready: boolean;
  tools: { name: string; description: string }[];
  languages: string[];
}

export interface ToolCall {
  tool: string;
  arguments: unknown;
  result?: string;
  error?: string;
}
