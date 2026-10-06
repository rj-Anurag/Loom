export interface User {
  display_name?: string;
  email?: string;
  avatar_url?: string;
}

export interface Project {
  id: string;
  name?: string;
  role?: string;
  created_at?: string;
  context_unit_count?: number;
  linked_chat_count?: number;
  agent_count?: number;
}

export interface Chat {
  chat_url: string;
  title?: string;
  platform?: string;
  linked_at?: string;
}

export interface TaskResultTest {
  command?: string;
  status?: "passed" | "failed" | "not_run" | string;
  summary?: string;
}

export interface ContextMetadata {
  task_name?: string;
  files_touched?: string[];
  tests?: TaskResultTest[];
  errors?: string[];
  blockers?: string[];
  next_steps?: string[];
  confidence?: number;
  conversation_role?: "user" | "assistant";
  turn_id?: string;
  message_id?: string;
  message_sequence?: number;
  session_title?: string;
  capture_method?: "live" | "import";
  [key: string]: unknown;
}

export interface ContextUnit {
  id?: string;
  content?: string;
  type?: string;
  trust_tier?: string;
  source_url?: string;
  source_type?: string;
  source_session_id?: string;
  agent_id?: string;
  agent_name?: string;
  metadata?: ContextMetadata;
  version?: number;
  parent_ids?: string[];
  created_at?: string;
  occurred_at?: string;
}

export type MemorySourceKind = "browser" | "session" | "unscoped";

export interface MemorySource {
  id: string;
  kind: MemorySourceKind;
  title: string;
  subtitle: string;
  source_type: string;
  source_session_id?: string;
  source_url?: string;
  agent_id?: string;
  agent_name?: string;
  platform?: string;
  linked_at?: string;
  unit_count: number;
  first_seen_at?: string;
  last_seen_at?: string;
}

export interface AuthPayload {
  user?: User;
  projects?: Project[];
  display_name?: string;
  email?: string;
  avatar_url?: string;
}

export interface HistoryPage {
  units?: ContextUnit[];
  has_more?: boolean;
  next_cursor?: string;
}

export interface ProjectSummary {
  summary: string;
  citations: (ContextUnit & { number: number; id: string; excerpt: string })[];
  context_count: number;
  updated_at: string | null;
  mode: "ai" | "extractive" | "fallback" | "empty" | "pending";
}
