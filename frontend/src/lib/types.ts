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

export interface ContextUnit {
  id?: string;
  content?: string;
  type?: string;
  trust_tier?: string;
  source_url?: string;
  created_at?: string;
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
