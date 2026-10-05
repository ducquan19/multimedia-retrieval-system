import type {
  KISQueryPlan,
  ObjectQueryTerm,
  PublicConfig,
  QueryType,
  SearchRequest,
  SearchSources,
  TrafficFilters,
} from "../../api/types";

/** Everything the search form holds; the request is derived from it without side effects. */
export interface SearchFormState {
  activeType: QueryType;
  topK: string;
  enhanceQuery: boolean;
  useReranking: boolean;
  sources: SearchSources;
  modelChoices: Array<"siglip" | "beit3">;
  objectTerms: ObjectQueryTerm[];
  kisQuery: string;
  queryUnderstanding: boolean;
  kisPlan: KISQueryPlan | null;
  includeTraffic: boolean;
  trafficQuery: string;
  trafficFilters: TrafficFilters;
  trakeMainQuery: string;
  eventQueries: string[];
  eventCount: number;
}

export function queryLengthError(label: string, query: string, maxLength: number): string | null {
  if (!query.trim()) {
    return `${label} không được để trống.`;
  }
  if (query.trim().length > maxLength) {
    return `${label} không được vượt quá ${maxLength} ký tự.`;
  }
  return null;
}

/** Traffic videos have no speech, so ASR is never offered for TRAFFIC. */
export function effectiveSources(activeType: QueryType, sources: SearchSources): SearchSources {
  return activeType === "TRAFFIC" ? { ...sources, asr: false } : sources;
}

/** The search request for the current form, or the validation errors that block it. */
export function buildSearchRequest(
  form: SearchFormState,
  config: PublicConfig,
): { payload: SearchRequest; errors: string[] } {
  const errors: string[] = [];
  const planned = form.activeType === "KIS" && form.queryUnderstanding;
  const sources = effectiveSources(form.activeType, form.sources);

  const parsedTopK = Number(form.topK);
  if (
    !Number.isInteger(parsedTopK) ||
    parsedTopK < config.min_top_k ||
    parsedTopK > config.max_top_k
  ) {
    errors.push(`Top-K phải là số nguyên từ ${config.min_top_k} đến ${config.max_top_k}.`);
  }
  if (!planned && !Object.values(sources).some(Boolean)) {
    errors.push("Chọn ít nhất một nguồn tìm kiếm.");
  }
  if (form.modelChoices.length === 0) {
    errors.push("Chọn ít nhất một model.");
  }
  const usesObjectSource = form.sources.object && !planned;
  if (usesObjectSource && form.objectTerms.length === 0 && !form.enhanceQuery) {
    errors.push("Thêm ít nhất một object hoặc bật Enhance query để tự chọn object.");
  }

  const common = {
    top_k: parsedTopK,
    enhance_query: planned ? false : form.enhanceQuery,
    use_reranking: form.useReranking,
    search_sources: sources,
    model_choices: form.modelChoices,
    ...(usesObjectSource && form.objectTerms.length > 0 ? { object_query: form.objectTerms } : {}),
  };

  if (form.activeType === "KIS") {
    const queryError = queryLengthError("Truy vấn KIS", form.kisQuery, config.max_query_length);
    if (queryError) errors.push(queryError);
    if (form.queryUnderstanding && !form.kisPlan) {
      errors.push("Hãy tạo và kiểm tra query plan trước khi tìm kiếm.");
    }
    if (form.queryUnderstanding && form.kisPlan) {
      if (!form.kisPlan.events.some((event) => event.importance === "anchor")) {
        errors.push("Query plan phải có ít nhất một anchor EVENT.");
      }
      for (const event of form.kisPlan.events) {
        if (!event.visual_query_en?.trim() && !event.asr_query_vi?.trim()) {
          errors.push(`EVENT ${event.event_index} phải có visual hoặc ASR query.`);
        }
      }
    }
    return {
      errors,
      payload: {
        query_type: "KIS",
        query: form.kisQuery.trim(),
        ...(form.queryUnderstanding && form.kisPlan
          ? { query_understanding: true, query_plan: form.kisPlan }
          : {}),
        include_traffic: form.includeTraffic,
        ...common,
      },
    };
  }

  if (form.activeType === "TRAFFIC") {
    const queryError = queryLengthError(
      "Truy vấn TRAFFIC",
      form.trafficQuery,
      config.max_query_length,
    );
    if (queryError) errors.push(queryError);
    const { clock_from: clockFrom, clock_to: clockTo } = form.trafficFilters;
    if (clockFrom && clockTo && clockFrom > clockTo) {
      errors.push("Giờ bắt đầu phải trước giờ kết thúc.");
    }
    return {
      errors,
      payload: {
        query_type: "TRAFFIC",
        query: form.trafficQuery.trim(),
        filters: form.trafficFilters,
        ...common,
      },
    };
  }

  const mainQuery = form.trakeMainQuery.trim();
  if (mainQuery.length > config.max_query_length) {
    errors.push(`Truy vấn chính không được vượt quá ${config.max_query_length} ký tự.`);
  }
  const events = form.eventQueries.slice(0, form.eventCount).map((query, index) => {
    const eventError = queryLengthError(`EVENT ${index + 1}`, query, config.max_query_length);
    if (eventError) errors.push(eventError);
    return { event_index: index + 1, query: query.trim() };
  });
  return {
    errors,
    payload: {
      query_type: "TRAKE",
      main_query: mainQuery || undefined,
      events,
      ...common,
    },
  };
}

