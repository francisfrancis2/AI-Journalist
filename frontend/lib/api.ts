/**
 * Typed API client for the AI Journalist FastAPI backend.
 * All types mirror the Pydantic schemas defined in backend/models/.
 */

import axios, { AxiosInstance } from "axios";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
}

export interface Story {
  id: string;
  title: string;
  topic: string;
  status: StoryStatus;
  tone: StoryTone;
  quality_score: number | null;
  word_count: number | null;
  estimated_duration_minutes: number | null;
  script_s3_key: string | null;
  error_message: string | null;
  iteration_count: number;
  created_at: string;
  updated_at: string;
}

export interface ScriptSection {
  section_number: number;
  title: string;
  narration: string;
  on_screen_text: string | null;
  b_roll_suggestions: string[];
  interview_cues: string[];
  estimated_seconds: number;
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
    title: string;
    url: string | null;
    credibility: "high" | "medium" | "low";
    type: string;
  }>;
  metadata: Record<string, unknown>;
}

export interface RawSource {
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

// ── Client ────────────────────────────────────────────────────────────────────

class AIJournalistAPIClient {
  private http: AxiosInstance;

  constructor(baseURL: string) {
    this.http = axios.create({
      baseURL,
      headers: { "Content-Type": "application/json" },
      timeout: 30_000,
    });

    // Global error interceptor
    this.http.interceptors.response.use(
      (res) => res,
      (err) => {
        const message =
          err.response?.data?.detail ??
          err.response?.data?.message ??
          err.message ??
          "Unknown error";
        return Promise.reject(new Error(message));
      }
    );
  }

  // ── Stories ──────────────────────────────────────────────────────────────

  async createStory(payload: StoryCreate): Promise<Story> {
    const { data } = await this.http.post<Story>("/api/v1/stories/", payload);
    return data;
  }

  async listStories(limit = 20, offset = 0, status?: StoryStatus): Promise<Story[]> {
    const params: Record<string, unknown> = { limit, offset };
    if (status) params.status = status;
    const { data } = await this.http.get<Story[]>("/api/v1/stories/", { params });
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

  async deleteStory(storyId: string): Promise<void> {
    await this.http.delete(`/api/v1/stories/${storyId}`);
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

  // ── Health ────────────────────────────────────────────────────────────────

  async healthCheck(): Promise<{ status: string; version: string }> {
    const { data } = await this.http.get("/health");
    return data;
  }
}

export const apiClient = new AIJournalistAPIClient(BASE_URL);
