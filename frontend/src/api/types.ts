export const QUERY_TYPES = ["TRAKE", "KIS", "TRAFFIC"] as const;
export type QueryType = (typeof QUERY_TYPES)[number];

export type TopK = number;

export interface SearchSources {
  image: boolean;
  asr: boolean;
  object: boolean;
}

export interface ObjectQueryTerm {
  label: string;
  min_count: number;
}

interface BaseSearchRequest {
  top_k: TopK;
  enhance_query: boolean;
  use_reranking: boolean;
  search_sources: SearchSources;
  model_choices: ("siglip" | "beit3")[];
  object_query?: ObjectQueryTerm[];
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

export type Daypart = "morning" | "midday" | "night";
export type Weather = "dry" | "wet";

export interface TrafficFilters {
  camera_ids: string[];
  dates: string[];
  dayparts: Daypart[];
  weathers: Weather[];
  clock_from?: string;
  clock_to?: string;
}

export interface TrafficSearchRequest extends BaseSearchRequest {
  query_type: "TRAFFIC";
  query: string;
  filters: TrafficFilters;
}

export type SearchRequest =
  | KISSearchRequest
  | VQASearchRequest
  | TRAKESearchRequest
  | TrafficSearchRequest;

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
  /** Original presentation time (ms) for VFR videos; absent -> frame_id / fps. */
  time_ms?: number | null;
  camera_name?: string | null;
  clock_time?: string | null;
  weather?: string | null;
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
  w_obj?: number;
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
  auto_object_query?: ObjectQueryTerm[];
  results: SingleSearchResult[];
}

export interface VQASearchResponse extends BaseSearchResponse {
  query_type: "VQA";
  auto_object_query?: ObjectQueryTerm[];
  results: SingleSearchResult[];
}

export interface TRAKESearchResponse extends BaseSearchResponse {
  query_type: "TRAKE";
  results: TRAKESearchResult[];
}

export interface TrafficSearchResponse extends BaseSearchResponse {
  query_type: "TRAFFIC";
  auto_object_query?: ObjectQueryTerm[];
  filtered_keyframes: number;
  results: SingleSearchResult[];
}

export type SearchResponse =
  | KISSearchResponse
  | VQASearchResponse
  | TRAKESearchResponse
  | TrafficSearchResponse;

export interface TrafficCamera {
  camera_id: string;
  name: string;
  streets: string[];
  video_ids: string[];
}

export interface TrafficOptions {
  available: boolean;
  cameras: TrafficCamera[];
  dates: string[];
  dayparts: Daypart[];
  weathers: Weather[];
}

export interface PublicConfig {
  min_top_k: number;
  max_top_k: number;
  default_top_k: number;
  max_trake_events: number;
  max_query_length: number;
  max_answer_length: number;
}

export interface ObjectLabelsResponse {
  available: boolean;
  labels: string[];
}

export interface DresEvaluation {
  id: string;
  name: string;
  type: string | null;
  status: string | null;
}

export type DresAnswer =
  | { mediaItemName: string; start: string; end: string }
  | { text: string };

export interface DresSubmitBody {
  answerSets: { answers: DresAnswer[] }[];
}

export interface DresSubmitRequest extends DresSubmitBody {
  evaluation_id: string;
  allow_duplicate?: boolean;
}

export interface DresSubmitResponse {
  accepted: boolean;
  status_code: number;
  submission: string | null;
  description: string | null;
  body: DresSubmitBody;
}

export interface VideoSourceResponse {
  video_id: string;
  url: string;
  source: "local" | "remote";
  fps: number;
  /** Original pts of the first frame: original ms = currentTime * 1000 + time_offset_ms. */
  time_offset_ms?: number;
}

export interface VideoKeyframe {
  frame_id: number;
  time_ms?: number | null;
  keyframe_url: string;
  segment_id: string;
  asr_text: string;
  objects: Record<string, unknown>[];
}

export interface VideoKeyframesResponse {
  video_id: string;
  /** Index in `keyframes` of the keyframe closest to the requested frame. */
  center_index: number;
  keyframes: VideoKeyframe[];
}
