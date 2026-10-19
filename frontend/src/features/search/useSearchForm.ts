import { type ClipboardEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { planKisQuery } from "../../api/client";
import type {
  KISQueryPlan,
  KISQueryPlanEvent,
  ObjectQueryTerm,
  PublicConfig,
  QueryType,
  SearchRequest,
  SearchSources,
  TrafficFilters,
} from "../../api/types";
import type { QueryHistoryEntry } from "./QueryHistory";
import { EMPTY_TRAFFIC_FILTERS } from "./TrafficFilterPanel";
import { buildSearchRequest, queryLengthError, type SearchFormState } from "./searchPayload";
import { parseTrakeEvents } from "./trakeEventParser";

export type ImageModel = "siglip" | "beit3";

/**
 * Every field of the search form, its validation errors and the KIS query planning.
 *
 * ``nextSignal`` aborts the previous request of the workspace (a search or a plan) and returns
 * the signal of the new one, so starting one always cancels the other.
 */
export function useSearchForm(config: PublicConfig, nextSignal: () => AbortSignal) {
  const [activeType, setActiveType] = useState<QueryType>("KIS");
  const [topK, setTopK] = useState(String(config.default_top_k));
  const [enhanceQuery, setEnhanceQuery] = useState(false);
  const [useReranking, setUseReranking] = useState(false);
  const [sources, setSources] = useState<SearchSources>({
    image: true,
    asr: false,
    object: false,
  });
  const [modelChoices, setModelChoices] = useState<ImageModel[]>(["siglip"]);
  const [objectTerms, setObjectTerms] = useState<ObjectQueryTerm[]>([]);
  const [kisQuery, setKisQuery] = useState("");
  const [queryUnderstanding, setQueryUnderstanding] = useState(false);
  const [kisPlan, setKisPlan] = useState<KISQueryPlan | null>(null);
  const [includeTraffic, setIncludeTraffic] = useState(false);
  const [trafficQuery, setTrafficQuery] = useState("");
  const [trafficFilters, setTrafficFilters] = useState<TrafficFilters>(EMPTY_TRAFFIC_FILTERS);
  const [trakeMainQuery, setTrakeMainQuery] = useState("");
  const initialEventCount = Math.min(3, config.max_trake_events);
  const [eventCount, setEventCount] = useState(initialEventCount);
  const [eventQueries, setEventQueries] = useState<string[]>(() =>
    Array.from({ length: initialEventCount }, () => ""),
  );
  const [validationErrors, setValidationErrors] = useState<string[]>([]);

  const planMutation = useMutation<
    KISQueryPlan,
    unknown,
    { query: string; signal: AbortSignal }
  >({
    mutationFn: ({ query, signal }) => planKisQuery(query, signal),
    onSuccess: (plan) => setKisPlan(plan),
  });

  const state: SearchFormState = {
    activeType,
    topK,
    enhanceQuery,
    useReranking,
    sources,
    modelChoices,
    objectTerms,
    kisQuery,
    queryUnderstanding,
    kisPlan,
    includeTraffic,
    trafficQuery,
    trafficFilters,
    trakeMainQuery,
    eventQueries,
    eventCount,
  };
  // KIS with Query Understanding searches with the plan; sources and Enhance are its own.
  const planned = activeType === "KIS" && queryUnderstanding;

  const changeEventCount = (nextCount: number) => {
    setEventQueries((current) => {
      if (current.length >= nextCount) {
        return current;
      }
      return [...current, ...Array.from({ length: nextCount - current.length }, () => "")];
    });
    setEventCount(nextCount);
  };

  const updateEventQuery = (index: number, value: string) => {
    setEventQueries((current) =>
      current.map((query, queryIndex) => (queryIndex === index ? value : query)),
    );
  };

  /** Pasting "E1: ...
E2: ..." anywhere in the TRAKE form fills every EVENT at once. */
  const pasteTrakeEvents = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const parsed = parseTrakeEvents(event.clipboardData.getData("text"));
    if (!parsed) return;
    event.preventDefault();
    if (parsed.events.length > config.max_trake_events) {
      setValidationErrors([
        `Đã dán ${parsed.events.length} EVENT, tối đa ${config.max_trake_events}. Chỉ giữ ${config.max_trake_events} EVENT đầu.`,
      ]);
    } else {
      setValidationErrors([]);
    }
    const count = Math.min(parsed.events.length, config.max_trake_events);
    if (parsed.mainQuery) setTrakeMainQuery(parsed.mainQuery);
    setEventQueries(parsed.events.slice(0, count));
    setEventCount(count);
  };

  const changeKisQuery = (value: string) => {
    setKisQuery(value);
    setKisPlan(null);
    planMutation.reset();
  };

  const toggleQueryUnderstanding = (enabled: boolean) => {
    setQueryUnderstanding(enabled);
    setKisPlan(null);
    planMutation.reset();
    if (enabled) setEnhanceQuery(false);
  };

  const understandKisQuery = () => {
    const queryError = queryLengthError("Truy vấn KIS", kisQuery, config.max_query_length);
    if (queryError) {
      setValidationErrors([queryError]);
      return;
    }
    setValidationErrors([]);
    planMutation.mutate({ query: kisQuery.trim(), signal: nextSignal() });
  };

  const setPlanSearchMode = (searchMode: KISQueryPlan["search_mode"]) => {
    setKisPlan((current) => (current ? { ...current, search_mode: searchMode } : current));
  };

  const updatePlanEvent = (index: number, update: Partial<KISQueryPlanEvent>) => {
    setKisPlan((current) =>
      current
        ? {
            ...current,
            events: current.events.map((event, eventIndex) =>
              eventIndex === index ? { ...event, ...update } : event,
            ),
          }
        : current,
    );
  };

  const removePlanEvent = (index: number) => {
    setKisPlan((current) => {
      if (!current || current.events.length === 1) return current;
      const remaining = current.events
        .filter((_, eventIndex) => eventIndex !== index)
        .map((event, eventIndex) => ({ ...event, event_index: eventIndex + 1 }));
      if (!remaining.some((event) => event.importance === "anchor")) {
        const firstEvent = remaining[0];
        if (firstEvent) remaining[0] = { ...firstEvent, importance: "anchor" };
      }
      return { ...current, events: remaining };
    });
  };

  const toggleModel = (model: ImageModel, enabled: boolean) =>
    setModelChoices((current) =>
      enabled ? [...current, model] : current.filter((item) => item !== model),
    );

  const toggleSource = (key: keyof SearchSources, enabled: boolean) =>
    setSources((current) => ({ ...current, [key]: enabled }));

  /** Require an object found in the results, and turn the object source on for it. */
  const pinObject = (term: ObjectQueryTerm) => {
    setObjectTerms((current) => [...current, term]);
    setSources((current) => ({ ...current, object: true }));
  };

  /** The request of the current form, or null with the reasons in validationErrors. */
  const buildPayload = (): SearchRequest | null => {
    const { payload, errors } = buildSearchRequest(state, config);
    setValidationErrors(errors);
    return errors.length === 0 ? payload : null;
  };

  /** Put every option of a past request back into the form. */
  const applyForm = (form: Partial<SearchFormState>) => {
    if (form.activeType) setActiveType(form.activeType);
    if (form.topK !== undefined) setTopK(form.topK);
    if (form.enhanceQuery !== undefined) setEnhanceQuery(form.enhanceQuery);
    if (form.useReranking !== undefined) setUseReranking(form.useReranking);
    if (form.sources) setSources(form.sources);
    if (form.modelChoices) setModelChoices(form.modelChoices);
    if (form.objectTerms) setObjectTerms(form.objectTerms);
    if (form.kisQuery !== undefined) {
      setKisQuery(form.kisQuery);
      planMutation.reset();
    }
    if (form.queryUnderstanding !== undefined) setQueryUnderstanding(form.queryUnderstanding);
    if (form.kisPlan !== undefined) setKisPlan(form.kisPlan);
    if (form.includeTraffic !== undefined) setIncludeTraffic(form.includeTraffic);
    if (form.trafficQuery !== undefined) setTrafficQuery(form.trafficQuery);
    if (form.trafficFilters) setTrafficFilters(form.trafficFilters);
    if (form.trakeMainQuery !== undefined) setTrakeMainQuery(form.trakeMainQuery);
    if (form.eventQueries) setEventQueries(form.eventQueries);
    if (form.eventCount !== undefined) setEventCount(form.eventCount);
  };

  /** History entries saved before the full request was stored only restore their text. */
  const restoreQueryText = (entry: QueryHistoryEntry) => {
    if (entry.type === "KIS") changeKisQuery(entry.query);
    else if (entry.type === "TRAFFIC") setTrafficQuery(entry.query);
    else {
      const count = Math.min(Math.max(entry.events.length, 1), config.max_trake_events);
      setTrakeMainQuery(entry.mainQuery);
      setEventQueries(
        Array.from({ length: Math.max(count, eventQueries.length) }, (_, index) =>
          entry.events[index] ?? "",
        ),
      );
      setEventCount(count);
    }
  };

  return {
    state,
    planned,
    validationErrors,
    setValidationErrors,
    planMutation,
    setActiveType,
    setTopK,
    setEnhanceQuery,
    setUseReranking,
    setObjectTerms,
    setIncludeTraffic,
    setTrafficQuery,
    setTrafficFilters,
    setTrakeMainQuery,
    changeEventCount,
    updateEventQuery,
    pasteTrakeEvents,
    changeKisQuery,
    toggleQueryUnderstanding,
    understandKisQuery,
    setPlanSearchMode,
    updatePlanEvent,
    removePlanEvent,
    toggleModel,
    toggleSource,
    pinObject,
    buildPayload,
    applyForm,
    restoreQueryText,
  };
}

export type SearchForm = ReturnType<typeof useSearchForm>;
