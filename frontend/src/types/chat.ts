export type ChatMode = "corpus" | "pdf" | "image";

export type MessageRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  createdAt: number;
  trace?: Trace | null;
  sources?: Source[];
  /** Si el mensaje está destacado/marcado con estrella. */
  starred?: boolean;
  /** Timestamp en que se destacó (para ordenar en el panel de destacados). */
  starredAt?: number;
}

export interface SourceMetadata {
  title?: string;
  source_url?: string;
  source_kind?: string;
  document_key?: string;
  [key: string]: unknown;
}

export interface Source {
  id: string;
  text: string;
  metadata?: SourceMetadata;
  distance?: number;
}

export interface TraceStep {
  title: string;
  detail: string;
}

export interface Trace {
  summary?: string;
  steps?: TraceStep[];
  retrieved_candidates?: number;
  curated_candidates?: number;
  intent?: string | null;
  evidence_policy?: string | null;
  dialogue_goal?: string | null;
  response_shape?: string | null;
  response_strategy?: string | null;
  answer_mode?: string | null;
  follow_up_policy?: string | null;
  needs_clarification?: boolean;
  active_document?: string | null;
  history_turns?: number;
  ocr_segments?: number;
  safety_mode?: boolean;
  risk_signals?: string[];
  selected_chunk_refs?: string[];
  retrieval_ms?: number;
  embedding_ms?: number;
  generation_ms?: number;
  total_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  estimated_external_cost_eur?: number;
  local_execution?: boolean;
  local_execution_note?: string | null;
  cost_measurement_note?: string | null;
}

export interface QueryResponse {
  answer: string;
  sources?: Source[];
  model?: string;
  mode?: ChatMode;
  session_id?: string;
  document_title?: string | null;
  trace?: Trace | null;
}

export interface BranchSnapshot {
  /** Mensajes desde el user (incluido) hasta el final del turno (incluyendo respuesta del asistente). */
  items: ChatMessage[];
}

export interface BranchSet {
  snapshots: BranchSnapshot[];
  index: number;
  /** Nº de ediciones del mensaje del usuario realizadas (límite 5). */
  editCount: number;
  /** Nº de regeneraciones de la respuesta del asistente (límite 5). */
  regenCount: number;
}

export interface Chat {
  id: string;
  sessionId: string;
  title: string;
  mode: ChatMode;
  documentTitle: string;
  messages: ChatMessage[];
  sources: Source[];
  trace: Trace | null;
  createdAt: number;
  updatedAt: number;
  /** Variantes por turno, indexadas por id del mensaje del usuario. */
  branches?: Record<string, BranchSet>;
  /** Si el chat está fijado en la parte superior del sidebar. */
  pinned?: boolean;
  /** Timestamp en que se fijó (para ordenar entre fijados). */
  pinnedAt?: number;
}
