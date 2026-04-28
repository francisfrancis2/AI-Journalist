/**
 * Typed API client for the AI Journalist FastAPI backend.
 * All types mirror the Pydantic schemas defined in backend/models/.
 */

import axios, { AxiosInstance } from "axios";
import type { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { getToken } from "@/lib/auth";

const API_TIMEOUT_MS = 60_000;

function isLocalHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function resolveBaseUrl(value: string | undefined): string {
  const configured = value?.trim() ?? "";
  if (!configured) return "";

  if (typeof window !== "undefined") {
    try {
      const target = new URL(configured);
      if (isLocalHostname(target.hostname) && !isLocalHostname(window.location.hostname)) {
        return "";
      }
    } catch {
      return configured;
    }
  }

  return configured.replace(/\/+$/, "");
}

const BASE_URL = resolveBaseUrl(process.env.NEXT_PUBLIC_API_URL);

// ── Types ─────────────────────────────────────────────────────────────────────

export type StoryTone =
  | "investigative"
  | "explanatory"
  | "narrative"
  | "profile"
  | "trend";

export type StoryStatus =
  | "pending"
  | "researching"
  | "analysing"
  | "writing_storyline"
  | "evaluating"
  | "scripting"
  | "completed"
  | "failed";

export interface StoryCreate {
  topic: string;
  title?: string;
  tone: StoryTone;
  target_duration_minutes?: number;
  target_audience?: string | null;
}

export interface EvaluationCriteria {
  factual_accuracy: number;
  narrative_coherence: number;
  audience_engagement: number;
  source_diversity: number;
  originality: number;
  production_feasibility: number;
}

export interface EvaluationData {
  criteria: EvaluationCriteria;
  overall_score: number;
  strengths: string[];
  weaknesses: string[];
  improvement_suggestions: string[];
  approved_for_scripting: boolean;
  evaluator_notes: string;
}

export interface BenchmarkData {
  bi_similarity_score: number;
  hook_potency: number;
  title_formula_fit: number;
  act_architecture: number;
  data_density: number;
  human_narrative_placement: number;
  tension_release_rhythm: number;
  closing_device: number;
  closest_reference_title: string | null;
  gaps: string[];
  strengths: string[];
  criterion_details?: Array<{
    criterion: string;
    label: string;
    score: number;
    assessment: string;
    improvement: string;
  }>;
  grade: string;
  library_key?: string;
  library_label?: string;
  library_version?: number | null;
  reference_doc_count?: number;
  built_at?: string | null;
  stale?: boolean;
  status_notes?: string[];
}

export interface BenchmarkLibraryStatus {
  key: string;
  label: string;
  description: string;
  implemented: boolean;
  active: boolean;
  available: boolean;
  ready_for_scoring: boolean;
  version: number | null;
  doc_count: number;
  minimum_doc_count: number;
  built_at: string | null;
  cache_exists: boolean;
  cache_mtime: string | null;
  stale: boolean;
  stale_after_days: number;
  notes: string[];
}

export interface BenchmarkAdminStatus {
  active_library_key: string;
  build_in_progress: boolean;
  build_library_key: string | null;
  requested_docs: number | null;
  last_build_started_at: string | null;
  last_build_finished_at: string | null;
  last_build_error: string | null;
  recommended_action: string;
  libraries: BenchmarkLibraryStatus[];
}

export interface BenchmarkReferenceDoc {
  id: string;
  youtube_id: string;
  title: string;
  description: string | null;
  view_count: number;
  like_count: number;
  duration_seconds: number;
  has_transcript: boolean;
  created_at: string;
}

export interface BenchmarkRebuildResponse {
  accepted: boolean;
  library_key: string;
  requested_docs: number;
  message: string;
}

export interface ScriptAuditCriteria {
  hook_strength: number;
  narrative_flow: number;
  evidence_and_specificity: number;
  pacing: number;
  writing_quality: number;
  production_readiness: number;
}

export interface ScriptSectionAudit {
  section_number: number;
  title: string;
  score: number;
  summary: string;
  strengths: string[];
  weaknesses: string[];
  benchmark_notes: string[];
  rewrite_recommendation: string;
}

export interface ScriptAuditBenchmarkComparison {
  closest_reference_title: string | null;
  alignment_summary: string;
  hook_comparison: string;
  structure_comparison: string;
  data_density_comparison: string;
  closing_comparison: string;
  best_in_class_takeaways: string[];
}

export interface ScriptAuditData {
  criteria: ScriptAuditCriteria;
  overall_score: number;
  grade: string;
  ready_for_production: boolean;
  audit_summary: string;
  strengths: string[];
  weaknesses: string[];
  rewrite_priorities: string[];
  section_audits: ScriptSectionAudit[];
  benchmark_comparison: ScriptAuditBenchmarkComparison | null;
}

export interface Story {
  id: string;
  title: string;
  topic: string;
  status: StoryStatus;
  tone: StoryTone;
  target_duration_minutes: number;
  target_audience: string | null;
  quality_score: number | null;
  word_count: number | null;
  estimated_duration_minutes: number | null;
  script_s3_key: string | null;
  error_message: string | null;
  iteration_count: number;
  evaluation_data: EvaluationData | null;
  benchmark_data: BenchmarkData | null;
  script_audit_data: ScriptAuditData | null;
  script_versions: ScriptVersion[] | null;
  created_at: string;
  updated_at: string;
}

export interface ScriptVersion {
  version: number;
  script: FinalScript;
  created_at: string;
  reason: string;
}

export interface ScriptSection {
  section_number: number;
  title: string;
  narration: string;
  estimated_seconds: number;
  source_ids?: string[];
}

export interface FinalScript {
  story_id: string;
  title: string;
  logline: string;
  opening_hook: string;
  sections: ScriptSection[];
  closing_statement: string;
  total_word_count: number;
  estimated_duration_minutes: number;
  sources: Array<{
    source_id?: string;
    title: string;
    url: string | null;
    credibility: "high" | "medium" | "low";
    type: string;
  }>;
  metadata: Record<string, unknown>;
}

export interface RawSource {
  source_id?: string;
  source_type: string;
  url: string | null;
  title: string;
  content: string;
  author: string | null;
  published_at: string | null;
  credibility: "high" | "medium" | "low";
  relevance_score: number;
  metadata: Record<string, unknown>;
}

export interface ResearchSource {
  source_id?: string | null;
  title: string;
  url: string | null;
  source_type: string;
  credibility: "high" | "medium" | "low";
  relevance_score: number;
  author: string | null;
  published_at: string | null;
  content_preview: string;
}

export interface FocusedResearchPlan {
  objective: string;
  evaluation_focus: string[];
  source_strategy: string[];
  source_strategy_reasoning: string;
  primary_queries: string[];
  deep_dive_queries: string[];
  financial_symbols: string[];
  rss_keyword: string;
  expected_improvements: string[];
}

export interface FocusedResearchRun {
  plan: FocusedResearchPlan;
  summary: string;
  sources: RawSource[];
}

export interface YouTubeVideo {
  title: string;
  url: string;
  channel: string;
  description: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  content: string;
  youtube_results: YouTubeVideo[];
}

// ── Client ────────────────────────────────────────────────────────────────────

class AIJournalistAPIClient {
  private http: AxiosInstance;

  constructor(baseURL: string) {
    this.http = axios.create({
      baseURL,
      headers: { "Content-Type": "application/json" },
      timeout: API_TIMEOUT_MS,
    });

    // Attach JWT token to every request
    this.http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
      const token = getToken();
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    });

    // Global error interceptor
    this.http.interceptors.response.use(
      (res: AxiosResponse) => res,
      (err: AxiosError<{ detail?: string; message?: string }>) => {
        const timedOut =
          err.code === "ECONNABORTED" ||
          err.message.toLowerCase().includes("timeout");

        if (timedOut) {
          return Promise.reject(new Error(
            "The backend did not respond in time. It may still be starting up; please try again in a moment."
          ));
        }

        const message =
          err.response?.data?.detail ??
          err.response?.data?.message ??
          err.message ??
          "Unknown error";
        return Promise.reject(new Error(message));
      }
    );
  }

  // ── Auth ─────────────────────────────────────────────────────────────────

  async login(email: string, password: string): Promise<{ access_token: string }> {
    const { data } = await this.http.post<{ access_token: string }>("/api/v1/auth/login", { email, password });
    return data;
  }

  async getMe(): Promise<{ id: string; email: string; is_active: boolean; is_admin: boolean; must_change_password: boolean; created_at: string }> {
    const { data } = await this.http.get("/api/v1/auth/me");
    return data;
  }

  async dismissPasswordChange(): Promise<void> {
    await this.http.post("/api/v1/auth/dismiss-password-change");
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await this.http.post("/api/v1/auth/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    });
  }

  async adminListUsers(): Promise<Array<{ id: string; email: string; is_active: boolean; is_admin: boolean; must_change_password: boolean; created_at: string }>> {
    const { data } = await this.http.get("/api/v1/admin/users");
    return data;
  }

  async adminCreateUser(email: string, password: string): Promise<{ id: string; email: string }> {
    const { data } = await this.http.post("/api/v1/admin/users", { email, password });
    return data;
  }

  async adminDeleteUser(userId: string): Promise<void> {
    await this.http.delete(`/api/v1/admin/users/${userId}`);
  }

  // ── Stories ──────────────────────────────────────────────────────────────

  async createStory(payload: StoryCreate): Promise<Story> {
    const { data } = await this.http.post<Story>("/api/v1/stories/", payload);
    return data;
  }

  async listStories(limit = 20, offset = 0, status?: StoryStatus): Promise<Story[]> {
    const params: Record<string, unknown> = { limit, offset };
    if (status) params.status = status;
    const { data } = await this.http.get<Story[]>("/api/v1/stories", { params });
    return data;
  }

  async getStory(storyId: string): Promise<Story> {
    const { data } = await this.http.get<Story>(`/api/v1/stories/${storyId}`);
    return data;
  }

  async getScript(storyId: string): Promise<FinalScript> {
    const { data } = await this.http.get<FinalScript>(
      `/api/v1/stories/${storyId}/script`
    );
    return data;
  }

  async rewriteStory(storyId: string): Promise<Story> {
    const { data } = await this.http.post<Story>(`/api/v1/stories/${storyId}/rewrite`);
    return data;
  }

  async regenerateScript(storyId: string): Promise<Story> {
    const { data } = await this.http.post<Story>(`/api/v1/stories/${storyId}/regenerate`);
    return data;
  }

  async implementRecommendations(storyId: string, recommendations: string[]): Promise<Story> {
    const { data } = await this.http.post<Story>(`/api/v1/stories/${storyId}/implement-recommendations`, { recommendations });
    return data;
  }

  async deleteStory(storyId: string): Promise<void> {
    await this.http.delete(`/api/v1/stories/${storyId}`);
  }

  async getResearchSources(storyId: string): Promise<ResearchSource[]> {
    const { data } = await this.http.get<ResearchSource[]>(
      `/api/v1/stories/${storyId}/sources`
    );
    return data;
  }

  async startFocusedResearch(
    storyId: string,
    objective: string
  ): Promise<FocusedResearchRun> {
    const { data } = await this.http.post<FocusedResearchRun>(
      `/api/v1/stories/${storyId}/focused-research`,
      { objective },
      { timeout: 180_000 }
    );
    return data;
  }

  async chat(
    storyId: string,
    message: string,
    history: ChatMessage[] = []
  ): Promise<ChatResponse> {
    const { data } = await this.http.post<ChatResponse>(
      `/api/v1/stories/${storyId}/chat`,
      { message, history }
    );
    return data;
  }

  // ── Research Tools ────────────────────────────────────────────────────────

  async webSearch(
    query: string,
    maxResults = 10,
    searchDepth: "basic" | "advanced" = "advanced"
  ): Promise<RawSource[]> {
    const { data } = await this.http.post<RawSource[]>(
      "/api/v1/research/web-search",
      { query, max_results: maxResults, search_depth: searchDepth }
    );
    return data;
  }

  async newsSearch(
    query: string,
    pageSize = 10,
    fromDaysAgo = 30
  ): Promise<RawSource[]> {
    const { data } = await this.http.post<RawSource[]>(
      "/api/v1/research/news",
      { query, page_size: pageSize, from_days_ago: fromDaysAgo }
    );
    return data;
  }

  async topHeadlines(
    query?: string,
    category?: string,
    country = "us"
  ): Promise<RawSource[]> {
    const { data } = await this.http.get<RawSource[]>(
      "/api/v1/research/news/headlines",
      { params: { query, category, country } }
    );
    return data;
  }

  async companyOverview(symbol: string): Promise<RawSource> {
    const { data } = await this.http.post<RawSource>(
      "/api/v1/research/financial/overview",
      { symbol }
    );
    return data;
  }

  async tickerSearch(
    keywords: string
  ): Promise<Array<{ symbol: string; name: string; type: string }>> {
    const { data } = await this.http.get(
      "/api/v1/research/financial/search",
      { params: { keywords } }
    );
    return data;
  }

  async dailyPrices(
    symbol: string,
    outputSize: "compact" | "full" = "compact"
  ): Promise<RawSource> {
    const { data } = await this.http.post<RawSource>(
      "/api/v1/research/financial/prices",
      { symbol },
      { params: { output_size: outputSize } }
    );
    return data;
  }

  async fetchRssFeed(
    url: string,
    maxEntries = 20,
    keyword?: string
  ): Promise<RawSource[]> {
    const { data } = await this.http.get<RawSource[]>(
      "/api/v1/research/rss/fetch",
      { params: { url, max_entries: maxEntries, keyword } }
    );
    return data;
  }

  async fetchDefaultFeeds(
    keyword?: string,
    maxPerFeed = 5
  ): Promise<RawSource[]> {
    const { data } = await this.http.get<RawSource[]>(
      "/api/v1/research/rss/defaults",
      { params: { keyword, max_per_feed: maxPerFeed } }
    );
    return data;
  }

  // ── Benchmark Admin ─────────────────────────────────────────────────────

  async getBenchmarkStatus(): Promise<BenchmarkAdminStatus> {
    const { data } = await this.http.get<BenchmarkAdminStatus>("/api/v1/benchmarks/status");
    return data;
  }

  async listBenchmarkLibraries(): Promise<BenchmarkLibraryStatus[]> {
    const { data } = await this.http.get<BenchmarkLibraryStatus[]>("/api/v1/benchmarks/libraries");
    return data;
  }

  async listBenchmarkReferences(
    limit = 25,
    offset = 0,
    libraryKey = "combined"
  ): Promise<BenchmarkReferenceDoc[]> {
    const { data } = await this.http.get<BenchmarkReferenceDoc[]>("/api/v1/benchmarks/references", {
      params: { limit, offset, library_key: libraryKey },
    });
    return data;
  }

  async rebuildBenchmarkLibrary(
    libraryKey = "combined"
  ): Promise<BenchmarkRebuildResponse> {
    const { data } = await this.http.post<BenchmarkRebuildResponse>(
      "/api/v1/benchmarks/rebuild",
      { library_key: libraryKey }
    );
    return data;
  }

  // ── Health ────────────────────────────────────────────────────────────────

  async healthCheck(): Promise<{ status: string; version: string }> {
    const { data } = await this.http.get("/health");
    return data;
  }

  streamStoryEvents(
    storyId: string,
    onStory: (story: Story) => void,
    onError?: (error: Error) => void
  ): () => void {
    const controller = new AbortController();
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers.Authorization = `Bearer ${token}`;

    fetch(`${BASE_URL}/api/v1/stories/${storyId}/events`, {
      headers,
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok || !response.body) {
          throw new Error(`Story stream failed: ${response.status}`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split("\n\n");
          buffer = events.pop() ?? "";
          for (const event of events) {
            const eventLine = event.split("\n").find((line) => line.startsWith("event: "));
            const dataLine = event.split("\n").find((line) => line.startsWith("data: "));
            if (!dataLine) continue;
            const eventName = eventLine?.slice(7);
            const payload = JSON.parse(dataLine.slice(6));
            if (eventName === "error") {
              throw new Error(payload.detail ?? "Story stream failed.");
            }
            onStory(payload as Story);
          }
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          onError?.(error instanceof Error ? error : new Error(String(error)));
        }
      });

    return () => controller.abort();
  }
}

export const apiClient = new AIJournalistAPIClient(BASE_URL);
