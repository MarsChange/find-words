import axios from 'axios';

// Always use relative '/api' path:
// - Dev mode: Vite proxy forwards /api → localhost:8000
// - Production (Electron): frontend is served by the same FastAPI server, so /api is same-origin
const BASE_URL = '/api';

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 300_000, // 5 min — large PDFs may take time to upload
  headers: {
    'Content-Type': 'application/json',
  },
});

/* ── Search ── */

export interface SearchParams {
  keyword: string;
  use_cbeta?: boolean;
  session_id?: number;
}

export interface SearchResultItem {
  source: string;
  file_id: number | null;
  filename: string;
  page_num: number | null;
  snippet: string;
  snippets?: string[];
  keyword_sentence?: string;
  is_original_text?: boolean;
  content_label?: string;
  dynasty: string;
  category: string;
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
    .post('/search', {
      query: params.keyword,
      use_cbeta: params.use_cbeta ?? false,
      session_id: params.session_id,
    })
    .then((r) => r.data);
}

export function getSessionResults(sessionId: number | string): Promise<SearchResultItem[]> {
  return api.get(`/sessions/${sessionId}/results`).then((r) => r.data.results ?? []);
}

/* ── Files ── */

export interface FileInfo {
  id: number;
  filename: string;
  dynasty: string;
  category: string;
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

export function reindexFile(fileId: number | string): Promise<void> {
  return api.post(`/files/${fileId}/reindex`).then(() => undefined);
}

export function updateFileMetadata(
  fileId: number | string,
  data: { dynasty?: string; category?: string; author?: string },
): Promise<FileInfo> {
  return api.patch(`/files/${fileId}`, data).then((r) => r.data);
}

export function getFileUrl(fileId: number | string): string {
  return `${BASE_URL}/files/${fileId}/content`;
}

/* ── Sessions ── */

export interface Session {
  id: number;
  keyword: string;
  traditional_keyword: string;
  synthesis: string;
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
  has_api_key?: boolean;
}

export function getSettings(): Promise<LLMSettings> {
  return api.get('/settings').then((r) => ({
    provider: r.data.llm_provider ?? 'DeepSeek',
    base_url: r.data.llm_provider_base_url ?? '',
    api_key: '',
    model: r.data.llm_model_name ?? '',
    has_api_key: r.data.has_api_key ?? false,
  }));
}

export function updateSettings(settings: LLMSettings): Promise<LLMSettings> {
  return api
    .put('/settings', {
      llm_provider: settings.provider || undefined,
      llm_provider_base_url: settings.base_url || undefined,
      llm_provider_api_key: settings.api_key || undefined,
      llm_model_name: settings.model || undefined,
    })
    .then((r) => ({
      provider: r.data.llm_provider ?? settings.provider,
      base_url: r.data.llm_provider_base_url ?? '',
      api_key: '',
      model: r.data.llm_model_name ?? '',
      has_api_key: r.data.has_api_key ?? false,
    }));
}

/* ── App Settings ── */

export interface AppSettings {
  cbeta_max_results: number;
  enable_thinking: boolean;
  ocr_model: string;
}

export function getAppSettings(): Promise<AppSettings> {
  return api.get('/settings/app').then((r) => ({
    cbeta_max_results: r.data.cbeta_max_results ?? 20,
    enable_thinking: r.data.enable_thinking ?? false,
    ocr_model: r.data.ocr_model ?? 'qwen3.5-plus',
  }));
}

export function updateAppSettings(settings: Partial<AppSettings>): Promise<AppSettings> {
  return api
    .patch('/settings/app', settings)
    .then((r) => ({
      cbeta_max_results: r.data.cbeta_max_results ?? 20,
      enable_thinking: r.data.enable_thinking ?? false,
      ocr_model: r.data.ocr_model ?? 'qwen3.5-plus',
    }));
}

export default api;
