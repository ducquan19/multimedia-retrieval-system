export const QUERY_TYPES = ["KIS", "VQA", "TRAKE"] as const;
export type QueryType = (typeof QUERY_TYPES)[number];

export type TopK = number;

export interface SearchSources {
  image: boolean;
  asr: boolean;
  object: boolean;
  ocr: boolean;
}

interface BaseSearchRequest {
  top_k: TopK;
  enhance_query: boolean;
  search_sources: SearchSources;
  model_choice: "siglip" | "beit3" | "hybrid";
}

export interface KISSearchRequest extends BaseSearchRequest {
  query_type: "KIS";
  query: string;
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
  main_query: string;
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
  ocr_text: string;
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
  ocr_text: string;
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

interface BaseSearchResponse {
  original_query: string;
  enhanced_query: string | null;
  retrieval_mode: "mock";
}

export interface KISSearchResponse extends BaseSearchResponse {
  query_type: "KIS";
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

export interface KISSubmissionRequest {
  query_type: "KIS";
  filename: string;
  rows: { video_id: string; frame_id: number }[];
}

export interface VQASubmissionRequest {
  query_type: "VQA";
  filename: string;
  rows: { video_id: string; frame_id: number; answer: string }[];
}

export interface TRAKESubmissionRequest {
  query_type: "TRAKE";
  filename: string;
  event_count: number;
  rows: { video_id: string; frame_ids: number[] }[];
}

export type SubmissionRequest =
  | KISSubmissionRequest
  | VQASubmissionRequest
  | TRAKESubmissionRequest;

export interface SubmissionRenderResponse {
  content: string;
  filename: string;
  row_count: number;
  warnings: string[];
}

export interface SubmissionDownload {
  blob: Blob;
  filename: string;
}

export interface PublicConfig {
  top_k_options: TopK[];
  default_top_k: TopK;
  max_trake_events: number;
  max_query_length: number;
  max_answer_length: number;
  retrieval_mode: "mock";
  gemini_mode: "mock";
}
