/**
 * Types of the backend API.
 *
 * Responses come straight from schema.gen.ts, generated from the backend's Pydantic models
 * (scripts/generate_api_types.py), so a renamed or retyped field fails the build.
 * Requests are written here to keep the optional fields the UI omits; ApiContract below
 * checks at compile time that each of them is still accepted by the backend.
 */
import type * as Api from "./schema.gen";

export const QUERY_TYPES = ["TRAKE", "KIS", "TRAFFIC"] as const;
export type QueryType = (typeof QUERY_TYPES)[number];

export type TopK = number;

export type SearchSources = Api.SearchSources;
export type ObjectQueryTerm = Api.ObjectQueryTerm;
export type KISQueryPlanEvent = Api.KISQueryPlanEvent;
export type KISQueryPlan = Api.KISQueryPlan;
export type KISSearchMode = KISQueryPlan["search_mode"];
export type KISEventImportance = KISQueryPlanEvent["importance"];

interface BaseSearchRequest {
  top_k: TopK;
  enhance_query: boolean;
  use_reranking: boolean;
  search_sources: SearchSources;
  model_choices: ("siglip" | "beit3")[];
  object_query?: ObjectQueryTerm[];
}

export interface KISSearchRequest extends BaseSearchRequest {
  query_type: "KIS";
  query: string;
  query_understanding?: boolean;
  query_plan?: KISQueryPlan;
  include_traffic?: boolean;
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

export type Daypart = Api.TrafficFilters["dayparts"][number];
export type Weather = Api.TrafficFilters["weathers"][number];

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

export type SingleSearchResult = Api.SingleSearchResult;
export type TRAKEEventResult = Api.TRAKEEventResult;
export type TRAKESearchResult = Api.TRAKESearchResult;
export type AppliedWeights = Api.AppliedWeights;
export type KISSearchResponse = Api.KISSearchResponse;
export type VQASearchResponse = Api.VQASearchResponse;
export type TRAKESearchResponse = Api.TRAKESearchResponse;
export type TrafficSearchResponse = Api.TrafficSearchResponse;

export type SearchResponse =
  | KISSearchResponse
  | VQASearchResponse
  | TRAKESearchResponse
  | TrafficSearchResponse;

/** Query by example: keyframes that look like one keyframe. */
export interface SimilarSearchRequest {
  video_id: string;
  frame_id: number;
  top_k: TopK;
  model_choices: ("siglip" | "beit3")[];
  include_traffic?: boolean;
}
export type SimilarSearchResponse = Api.SimilarSearchResponse;
/** A response the single-frame result grid can show. */
export type SingleFrameResponse =
  | KISSearchResponse
  | VQASearchResponse
  | TrafficSearchResponse
  | SimilarSearchResponse;

export type TrafficCamera = Api.TrafficCamera;
export type TrafficOptions = Api.TrafficOptionsResponse;
export type PublicConfig = Api.PublicConfigResponse;
export type ObjectLabelsResponse = Api.ObjectLabelsResponse;
export type DresEvaluation = Api.DresEvaluation;
export type DresSubmissionRecord = Api.DresSubmissionRecord;

export type DresAnswer =
  | { mediaItemName: string; start: string; end: string }
  | { text: string };

export interface DresSubmitBody {
  answerSets: { answers: DresAnswer[] }[];
}

export interface DresSubmitRequest extends DresSubmitBody {
  evaluation_id: string;
}

export type DresSubmitResponse = Omit<Api.DresSubmitResponse, "body"> & {
  /** The body that was forwarded to DRES. */
  body: DresSubmitBody;
};

export type VideoSourceResponse = Api.VideoSourceResponse;
export type VideoKeyframe = Api.VideoKeyframe;
export type VideoKeyframesResponse = Api.VideoKeyframesResponse;

/** Compile-time only: a request type that no longer matches the backend breaks the build. */
type Accepts<Backend, Sent extends Backend> = [Backend, Sent];
export type ApiContract = [
  Accepts<Api.KISSearchRequestInput, KISSearchRequest>,
  Accepts<Api.VQASearchRequestInput, VQASearchRequest>,
  Accepts<Api.TRAKESearchRequestInput, TRAKESearchRequest>,
  Accepts<Api.TrafficSearchRequestInput, TrafficSearchRequest>,
  Accepts<Api.DresSubmitRequestInput, DresSubmitRequest>,
  Accepts<Api.KISQueryPlanRequestInput, { query: string }>,
  Accepts<Api.SimilarSearchRequestInput, SimilarSearchRequest>,
];
