export const QUERY_TYPES = ["KIS", "VQA", "TRAKE"] as const;
export type QueryType = (typeof QUERY_TYPES)[number];

export type TopK = number;

export interface SearchSources {
  image: boolean;
  asr: boolean;
  object: boolean;
}

interface BaseSearchRequest {
  top_k: TopK;
  enhance_query: boolean;
  use_reranking: boolean;
  search_sources: SearchSources;
  model_choices: ("siglip" | "beit3")[];
}

export type KISSearchMode = "single_anchor" | "multi_anchor" | "temporal_sequence";
export type KISEventImportance = "anchor" | "supporting" | "context";

export interface KISQueryPlanEvent {
  event_index: number;
  source_span_vi: string;
  visual_query_en: string | null;
  asr_query_vi: string | null;
  importance: KISEventImportance;
  confidence: number;
  inferred: boolean;
}

export interface KISQueryPlan {
  search_mode: KISSearchMode;
  events: KISQueryPlanEvent[];
  warnings: string[];
  planner_model: string;
}

export interface KISSearchRequest extends BaseSearchRequest {
  query_type: "KIS";
  query: string;
  query_understanding?: boolean;
  query_plan?: KISQueryPlan;
}

export interface VQASearchRequest extends BaseSearchRequest {
  query_type: "VQA";
  query: string;
}

export interface TRAKEEventQuery {
  event_index: number;
  query: string;
}

export interface TRAKESearchRequest extends BaseSearchRequest {
  query_type: "TRAKE";
  main_query?: string;
  events: TRAKEEventQuery[];
}

export type SearchRequest = KISSearchRequest | VQASearchRequest | TRAKESearchRequest;

export interface SingleSearchResult {
  result_id: string;
  rank: number;
  video_id: string;
  frame_id: number;
  keyframe_url: string;
  segment_id: string;
  asr_text: string;
  objects: Record<string, unknown>[];
  similarity_score: number;
  answer: string;
}

export interface TRAKEEventResult {
  event_index: number;
  frame_id: number;
  keyframe_url: string;
  segment_id: string;
  asr_text: string;
  objects: Record<string, unknown>[];
  similarity_score: number;
}

export interface TRAKESearchResult {
  result_id: string;
  rank: number;
  video_id: string;
  similarity_score: number;
  events: TRAKEEventResult[];
}

export interface AppliedWeights {
  w_vis: number;
  w_asr: number;
}

interface BaseSearchResponse {
  original_query: string;
  enhanced_query: string | null;
  model_choices: string[];
  applied_weights: AppliedWeights | null;
  warnings: string[];
}

export interface KISSearchResponse extends BaseSearchResponse {
  query_type: "KIS";
  query_plan?: KISQueryPlan | null;
  results: SingleSearchResult[];
}

export interface VQASearchResponse extends BaseSearchResponse {
  query_type: "VQA";
  results: SingleSearchResult[];
}

export interface TRAKESearchResponse extends BaseSearchResponse {
  query_type: "TRAKE";
  results: TRAKESearchResult[];
}

export type SearchResponse = KISSearchResponse | VQASearchResponse | TRAKESearchResponse;

export interface PublicConfig {
  min_top_k: number;
  max_top_k: number;
  default_top_k: number;
  max_trake_events: number;
  max_query_length: number;
  max_answer_length: number;
}

export interface VideoSourceResponse {
  video_id: string;
  url: string;
  source: "local" | "remote";
  fps: number;
}
