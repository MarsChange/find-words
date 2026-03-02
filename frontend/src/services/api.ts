import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

/* ── Search ── */

export interface SearchParams {
  keyword: string;
  use_cbeta?: boolean;
}

export interface SearchResultItem {
  source: string;
  file_id: number | null;
  filename: string;
  page_num: number | null;
  snippet: string;
  dynasty: string;
  author: string;
}

export interface SearchResponse {
  query: string;
  traditional_query: string;
  hits: SearchResultItem[];
  total: number;
}

export function search(params: SearchParams): Promise<SearchResponse> {
  return api
    .post('/search', { query: params.keyword, use_cbeta: params.use_cbeta ?? false })
    .then((r) => r.data);
}

/* ── Files ── */

export interface FileInfo {
  id: number;
  filename: string;
  dynasty: string;
  author: string;
  status: string;
  page_count: number;
}

export function listFiles(): Promise<FileInfo[]> {
  return api.get('/files').then((r) => r.data.files ?? []);
}

export function uploadFile(file: File): Promise<{ id: number; filename: string; status: string }> {
  const form = new FormData();
  form.append('file', file);
  return api
    .post('/files', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
}

export function uploadFiles(files: File[]): Promise<void> {
  return Promise.all(files.map((f) => uploadFile(f))).then(() => undefined);
}

export function deleteFile(fileId: number | string): Promise<void> {
  return api.delete(`/files/${fileId}`).then(() => undefined);
}

export function getFileUrl(fileId: number | string): string {
  return `/api/files/${fileId}/content`;
}

/* ── Sessions ── */

export interface Session {
  id: number;
  keyword: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface SessionMessage {
  id: number;
  session_id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export function getSessions(): Promise<Session[]> {
  return api.get('/sessions').then((r) => r.data.sessions ?? []);
}

export function getSession(
  sessionId: number | string,
): Promise<{ session: Session; messages: SessionMessage[] }> {
  return api.get(`/sessions/${sessionId}`).then((r) => r.data);
}

export function createSession(keyword: string): Promise<Session> {
  return api.post('/sessions', { keyword }).then((r) => r.data);
}

export function deleteSession(sessionId: number | string): Promise<void> {
  return api.delete(`/sessions/${sessionId}`).then(() => undefined);
}

/* ── Chat ── */

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatRequest {
  message: string;
  session_id?: number;
  history: ChatMessage[];
}

export interface ChatResponse {
  reply: string;
}

export function chat(req: ChatRequest): Promise<ChatResponse> {
  return api.post('/chat', req).then((r) => r.data);
}

/* ── Settings ── */

export interface LLMSettings {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
}

export function getSettings(): Promise<LLMSettings> {
  return api.get('/settings').then((r) => ({
    provider: r.data.llm_provider ?? 'DeepSeek',
    base_url: r.data.llm_provider_base_url ?? '',
    api_key: r.data.has_api_key ? '********' : '',
    model: r.data.llm_model_name ?? '',
  }));
}

export function updateSettings(settings: LLMSettings): Promise<LLMSettings> {
  return api
    .put('/settings', {
      llm_provider: settings.provider || undefined,
      llm_provider_base_url: settings.base_url || undefined,
      llm_provider_api_key: settings.api_key === '********' ? undefined : settings.api_key || undefined,
      llm_model_name: settings.model || undefined,
    })
    .then((r) => ({
      provider: r.data.llm_provider ?? settings.provider,
      base_url: r.data.llm_provider_base_url ?? '',
      api_key: r.data.has_api_key ? '********' : '',
      model: r.data.llm_model_name ?? '',
    }));
}

export default api;
