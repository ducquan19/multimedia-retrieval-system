import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { type UseMutationResult, useMutation } from "@tanstack/react-query";

import { friendlySearchError, planKisQuery, search } from "../../api/client";
import {
  QUERY_TYPES,
  type KISQueryPlan,
  type KISQueryPlanEvent,
  type ObjectQueryTerm,
  type PublicConfig,
  type QueryType,
  type SearchRequest,
  type SearchResponse,
  type SearchSources,
} from "../../api/types";
import { SingleResultInspector } from "../results/SingleResultInspector";
import { TrakeResultInspector } from "../results/TrakeResultInspector";
import { VideoLookup } from "../results/VideoLookup";
import { ObjectQueryInput } from "./ObjectQueryInput";
import { SearchInsight } from "./SearchInsight";

const SOURCE_OPTIONS: { key: keyof SearchSources; label: string }[] = [
  { key: "image", label: "Image" },
  { key: "asr", label: "ASR" },
  { key: "object", label: "Object" },
];

type GroupSort = "score" | "time";
type ProgramFilter = "ALL" | "L21_L22" | "L23" | "L24" | "L25" | "L26";
const DARK_MODE_STORAGE_KEY = "aic-retrieval-theme";
const PROGRAM_PREFIXES: Record<Exclude<ProgramFilter, "ALL">, readonly string[]> = {
  L21_L22: ["L21", "L22"],
  L23: ["L23"],
  L24: ["L24"],
  L25: ["L25"],
  L26: ["L26"],
};

function matchesProgram(videoId: string, program: ProgramFilter): boolean {
  return (
    program === "ALL" || PROGRAM_PREFIXES[program].some((prefix) => videoId.startsWith(prefix))
  );
}

function prefersDarkMode(): boolean {
  try {
    const storedTheme = window.localStorage.getItem(DARK_MODE_STORAGE_KEY);
    if (storedTheme === "dark") return true;
    if (storedTheme === "light") return false;
  } catch {
    // Fall through to the operating-system preference when storage is unavailable.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

interface SearchMutationVariables {
  payload: SearchRequest;
  signal: AbortSignal;
}

interface SearchWorkspaceProps {
  config: PublicConfig;
}

function queryLengthError(label: string, query: string, maxLength: number): string | null {
  if (!query.trim()) {
    return `${label} không được để trống.`;
  }
  if (query.trim().length > maxLength) {
    return `${label} không được vượt quá ${maxLength} ký tự.`;
  }
  return null;
}

export function SearchWorkspace({ config }: SearchWorkspaceProps) {
  const [isDarkMode, setIsDarkMode] = useState(prefersDarkMode);
  const [activeType, setActiveType] = useState<QueryType>("KIS");
  const [topK, setTopK] = useState(String(config.default_top_k));
  const [enhanceQuery, setEnhanceQuery] = useState(false);
  const [useReranking, setUseReranking] = useState(false);
  const [sources, setSources] = useState<SearchSources>({
    image: true,
    asr: false,
    object: false,
  });
  const [modelChoices, setModelChoices] = useState<Array<"siglip" | "beit3">>(["siglip"]);
  const [objectTerms, setObjectTerms] = useState<ObjectQueryTerm[]>([]);
  const [kisQuery, setKisQuery] = useState("");
  const [queryUnderstanding, setQueryUnderstanding] = useState(false);
  const [kisPlan, setKisPlan] = useState<KISQueryPlan | null>(null);
  const [vqaQuery, setVqaQuery] = useState("");
  const [trakeMainQuery, setTrakeMainQuery] = useState("");
  const initialEventCount = Math.min(3, config.max_trake_events);
  const [eventCount, setEventCount] = useState(initialEventCount);
  const [eventQueries, setEventQueries] = useState<string[]>(() =>
    Array.from({ length: initialEventCount }, () => ""),
  );
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const [groupByVideo, setGroupByVideo] = useState(false);
  const [groupSort, setGroupSort] = useState<GroupSort>("score");
  const [programFilter, setProgramFilter] = useState<ProgramFilter>("ALL");
  const activeController = useRef<AbortController | null>(null);

  const [normalSidebarWidth, setNormalSidebarWidth] = useState<number>(400);
  const [sidebarWidth, setSidebarWidth] = useState<number>(400);
  const [isResizing, setIsResizing] = useState<boolean>(false);

  const startResizing = (mouseDownEvent: React.MouseEvent) => {
    mouseDownEvent.preventDefault();
    setIsResizing(true);
    const startX = mouseDownEvent.clientX;
    const startWidth = sidebarWidth;

    const doDrag = (dragEvent: MouseEvent) => {
      const maxAllowed = Math.max(800, Math.min(Math.round(window.innerWidth * 0.65), 1050));
      const nextWidth = Math.max(280, Math.min(maxAllowed, startWidth + dragEvent.clientX - startX));
      setSidebarWidth(nextWidth);
      if (!queryUnderstanding || activeType !== "KIS") {
        setNormalSidebarWidth(nextWidth);
      }
    };

    const stopDrag = () => {
      document.documentElement.removeEventListener('mousemove', doDrag, false);
      document.documentElement.removeEventListener('mouseup', stopDrag, false);
      document.body.style.cursor = '';
      setIsResizing(false);
    };

    document.documentElement.addEventListener('mousemove', doDrag, false);
    document.documentElement.addEventListener('mouseup', stopDrag, false);
    document.body.style.cursor = 'col-resize';
  };

  const searchMutation = useMutation<SearchResponse, unknown, SearchMutationVariables>({
    mutationFn: ({ payload, signal }) => search(payload, signal),
  });
  const planMutation = useMutation<
    KISQueryPlan,
    unknown,
    { query: string; signal: AbortSignal }
  >({
    mutationFn: ({ query, signal }) => planKisQuery(query, signal),
    onSuccess: (plan) => {
      setKisPlan(plan);
      setSidebarWidth((prev) => Math.max(prev, 550));
    },
  });
  const displayedResultCount =
    searchMutation.data?.results.filter((result) =>
      matchesProgram(result.video_id, programFilter),
    ).length ?? 0;
  const showProgramFilter =
    !searchMutation.isPending && Boolean(searchMutation.data?.results.length);

  useEffect(
    () => () => {
      activeController.current?.abort();
    },
    [],
  );

  useEffect(() => {
    const theme = isDarkMode ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(DARK_MODE_STORAGE_KEY, theme);
    } catch {
      // The visual preference still applies for this session when storage is unavailable.
    }
  }, [isDarkMode]);

  const changeTab = (queryType: QueryType) => {
    activeController.current?.abort();
    searchMutation.reset();
    planMutation.reset();
    setValidationErrors([]);
    setActiveType(queryType);
    if (queryType !== "KIS") {
      setSidebarWidth(normalSidebarWidth);
    } else if (queryUnderstanding) {
      setSidebarWidth((prev) => Math.max(prev, 550));
    }
  };

  const changeEventCount = (nextCount: number) => {
    setEventQueries((current) => {
      if (current.length >= nextCount) {
        return current;
      }
      return [
        ...current,
        ...Array.from({ length: nextCount - current.length }, () => ""),
      ];
    });
    setEventCount(nextCount);
  };

  const updateEventQuery = (index: number, value: string) => {
    setEventQueries((current) =>
      current.map((query, queryIndex) => (queryIndex === index ? value : query)),
    );
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
    if (enabled) {
      setEnhanceQuery(false);
      setSidebarWidth((prev) => Math.max(prev, 550));
    } else {
      setSidebarWidth(normalSidebarWidth);
    }
  };

  const understandKisQuery = () => {
    const queryError = queryLengthError("Query KIS", kisQuery, config.max_query_length);
    if (queryError) {
      setValidationErrors([queryError]);
      return;
    }
    setValidationErrors([]);
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    planMutation.mutate({ query: kisQuery.trim(), signal: controller.signal });
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

  const buildPayload = (): SearchRequest | null => {
    const errors: string[] = [];
    const parsedTopK = Number(topK);
    if (
      !Number.isInteger(parsedTopK) ||
      parsedTopK < config.min_top_k ||
      parsedTopK > config.max_top_k
    ) {
      errors.push(
        `Top-K phải là số nguyên từ ${config.min_top_k} đến ${config.max_top_k}.`,
      );
    }
    if (
      !(activeType === "KIS" && queryUnderstanding) &&
      !Object.values(sources).some(Boolean)
    ) {
      errors.push("Chọn ít nhất một nguồn tìm kiếm.");
    }
    if (modelChoices.length === 0) {
      errors.push("Chọn ít nhất một model.");
    }
    const usesObjectSource = sources.object && !(activeType === "KIS" && queryUnderstanding);
    if (usesObjectSource && objectTerms.length === 0 && !enhanceQuery) {
      errors.push("Thêm ít nhất một object hoặc bật Enhance query để tự chọn object.");
    }

    const common = {
      top_k: parsedTopK,
      enhance_query: activeType === "KIS" && queryUnderstanding ? false : enhanceQuery,
      use_reranking: useReranking,
      search_sources: sources,
      model_choices: modelChoices,
      ...(usesObjectSource && objectTerms.length > 0 ? { object_query: objectTerms } : {}),
    };

    let payload: SearchRequest;
    if (activeType === "KIS") {
      const queryError = queryLengthError("Query KIS", kisQuery, config.max_query_length);
      if (queryError) errors.push(queryError);
      if (queryUnderstanding && !kisPlan) {
        errors.push("Hãy tạo và kiểm tra query plan trước khi tìm kiếm.");
      }
      if (queryUnderstanding && kisPlan) {
        if (!kisPlan.events.some((event) => event.importance === "anchor")) {
          errors.push("Query plan phải có ít nhất một anchor EVENT.");
        }
        kisPlan.events.forEach((event) => {
          if (
            !event.visual_query_en?.trim() &&
            !event.asr_query_vi?.trim()
          ) {
            errors.push(`EVENT ${event.event_index} phải có visual hoặc ASR query.`);
          }
        });
      }
      payload = {
        query_type: "KIS",
        query: kisQuery.trim(),
        ...(queryUnderstanding && kisPlan
          ? { query_understanding: true, query_plan: kisPlan }
          : {}),
        ...common,
      };
    } else if (activeType === "VQA") {
      const queryError = queryLengthError("Câu hỏi VQA", vqaQuery, config.max_query_length);
      if (queryError) errors.push(queryError);
      payload = { query_type: "VQA", query: vqaQuery.trim(), ...common };
    } else {
      if (trakeMainQuery.trim() && trakeMainQuery.trim().length > config.max_query_length) {
        errors.push(`Main query TRAKE không được vượt quá ${config.max_query_length} ký tự.`);
      }
      const events = eventQueries.slice(0, eventCount).map((query, index) => {
        const eventError = queryLengthError(
          `EVENT ${index + 1}`,
          query,
          config.max_query_length,
        );
        if (eventError) errors.push(eventError);
        return { event_index: index + 1, query: query.trim() };
      });
      payload = {
        query_type: "TRAKE",
        main_query: trakeMainQuery.trim() || undefined,
        events,
        ...common,
      };
    }

    setValidationErrors(errors);
    return errors.length === 0 ? payload : null;
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload = buildPayload();
    if (!payload) return;

    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    setGroupByVideo(false);
    setGroupSort("score");
    searchMutation.mutate({ payload, signal: controller.signal });
  };

  const submitQueryOnEnter = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== "Enter" ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    ) {
      return;
    }
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  };

  return (
    <section className="workspace" aria-label="Retrieval workspace">
      <aside
        className="workspace__sidebar"
        aria-label="Query controls"
        style={{
          width: sidebarWidth,
          flexShrink: 0,
          transition: isResizing ? "none" : "width 0.24s cubic-bezier(0.4, 0, 0.2, 1)",
        }}
      >
        <header className="workspace__brand">
          <span>Media Retrieval System</span>
          <label className="theme-switch">
            <span className="visually-hidden">Dark mode</span>
            <input
              type="checkbox"
              role="switch"
              aria-label="Dark mode"
              checked={isDarkMode}
              onChange={(event) => setIsDarkMode(event.target.checked)}
            />
            <span className="theme-switch__track" aria-hidden="true">
              <span className="theme-switch__thumb" />
            </span>
          </label>
        </header>

        <div className="query-tabs" role="tablist" aria-label="Query type">
          {QUERY_TYPES.map((queryType) => (
            <button
              key={queryType}
              id={`tab-${queryType}`}
              type="button"
              role="tab"
              aria-selected={activeType === queryType}
              aria-controls={`panel-${queryType}`}
              className="query-tab"
              onClick={() => changeTab(queryType)}
            >
              <strong>{queryType}</strong>
            </button>
          ))}
        </div>

        <form id="search-form" className="search-layout" onSubmit={submitSearch} noValidate>
        <div
          id={`panel-${activeType}`}
          role="tabpanel"
          aria-labelledby={`tab-${activeType}`}
          className="query-panel"
        >
          {activeType === "KIS" && (
            <div className="kis-query-zone">
              <label className="field field--query-only" htmlFor="kis-query">
                <span>Query KIS</span>
                <textarea
                  id="kis-query"
                  value={kisQuery}
                  maxLength={config.max_query_length}
                  onChange={(event) => changeKisQuery(event.target.value)}
                  onKeyDown={submitQueryOnEnter}
                  aria-keyshortcuts="Enter Shift+Enter"
                  placeholder="Enter a KIS query"
                  rows={6}
                />
              </label>

              <section className="query-planning-card">
                <div className="query-planning-card__header">
                  <label className="query-planning-toggle" htmlFor="query-understanding">
                    <strong>Multi-Event Planning</strong>
                    <input
                      id="query-understanding"
                      type="checkbox"
                      aria-label="Query Decomposition"
                      checked={queryUnderstanding}
                      onChange={(event) => toggleQueryUnderstanding(event.target.checked)}
                    />
                  </label>

                  {queryUnderstanding && (
                    <button
                      type="button"
                      className="query-plan__generate"
                      onClick={understandKisQuery}
                      disabled={planMutation.isPending}
                    >
                      {planMutation.isPending ? "Executing…" : "Execute"}
                    </button>
                  )}
                </div>

                {queryUnderstanding && (planMutation.isError || kisPlan) && (
                  <section className="query-plan" aria-label="KIS query plan">
                  {planMutation.isError && (
                    <p className="query-plan__error" role="alert">
                      {friendlySearchError(planMutation.error)}
                    </p>
                  )}

                  {kisPlan && (
                    <>
                      <label className="field field--compact" htmlFor="kis-search-mode">
                        <span>Search strategy</span>
                        <select
                          id="kis-search-mode"
                          value={kisPlan.search_mode}
                          onChange={(event) =>
                            setKisPlan((current) =>
                              current
                                ? {
                                    ...current,
                                    search_mode: event.target
                                      .value as KISQueryPlan["search_mode"],
                                  }
                                : current,
                            )
                          }
                        >
                          <option value="single_anchor">Single anchor</option>
                          <option value="multi_anchor">Multiple anchors</option>
                          <option value="temporal_sequence">Temporal sequence</option>
                        </select>
                      </label>

                      <div className="query-plan__events">
                        {kisPlan.events.map((planEvent, index) => (
                          <article className="query-plan-event" key={planEvent.event_index}>
                            <header>
                              <strong>EVENT {planEvent.event_index}</strong>
                              <span>{Math.round(planEvent.confidence * 100)}% confidence</span>
                              <button
                                type="button"
                                onClick={() => removePlanEvent(index)}
                                disabled={kisPlan.events.length === 1}
                                aria-label={`Remove EVENT ${planEvent.event_index}`}
                              >
                                Remove
                              </button>
                            </header>
                            <p className="query-plan-event__source">{planEvent.source_span_vi}</p>
                            <div className="query-plan-event__fields">
                              <label className="field">
                                <span>Visual query (English)</span>
                                <textarea
                                  aria-label={`Visual query EVENT ${planEvent.event_index}`}
                                  value={planEvent.visual_query_en ?? ""}
                                  onChange={(event) =>
                                    updatePlanEvent(index, {
                                      visual_query_en: event.target.value || null,
                                    })
                                  }
                                  rows={2}
                                />
                              </label>
                              <label className="field">
                                <span>ASR query (Vietnamese)</span>
                                <textarea
                                  aria-label={`ASR query EVENT ${planEvent.event_index}`}
                                  value={planEvent.asr_query_vi ?? ""}
                                  onChange={(event) =>
                                    updatePlanEvent(index, {
                                      asr_query_vi: event.target.value || null,
                                    })
                                  }
                                  rows={2}
                                />
                              </label>
                            </div>
                            <label className="field field--compact">
                              <span>Importance</span>
                              <select
                                aria-label={`Importance EVENT ${planEvent.event_index}`}
                                value={planEvent.importance}
                                onChange={(event) =>
                                  updatePlanEvent(index, {
                                    importance: event.target
                                      .value as KISQueryPlanEvent["importance"],
                                  })
                                }
                              >
                                <option value="anchor">Anchor</option>
                                <option value="supporting">Supporting</option>
                                <option value="context">Context</option>
                              </select>
                            </label>
                            {planEvent.inferred && (
                              <small className="query-plan-event__inferred">
                                Contains an inference — verify before searching.
                              </small>
                            )}
                          </article>
                        ))}
                      </div>

                      {kisPlan.warnings.map((warning) => (
                        <p className="query-plan__warning" key={warning}>
                          {warning}
                        </p>
                      ))}
                    </>
                  )}
                  </section>
                )}
              </section>
            </div>
          )}

          {activeType === "VQA" && (
            <label className="field field--query-only" htmlFor="vqa-query">
              <span>Query VQA</span>
              <textarea
                id="vqa-query"
                value={vqaQuery}
                maxLength={config.max_query_length}
                onChange={(event) => setVqaQuery(event.target.value)}
                onKeyDown={submitQueryOnEnter}
                aria-keyshortcuts="Enter Shift+Enter"
                rows={6}
              />
            </label>
          )}

          {activeType === "TRAKE" && (
            <div className="trake-fields">
              <label className="field" htmlFor="trake-main-query">
                <span>Main query TRAKE</span>
                <textarea
                  id="trake-main-query"
                  value={trakeMainQuery}
                  maxLength={config.max_query_length}
                  onChange={(event) => setTrakeMainQuery(event.target.value)}
                  onKeyDown={submitQueryOnEnter}
                  aria-keyshortcuts="Enter Shift+Enter"
                  rows={3}
                />
              </label>

              <label className="trake-event-count-row" htmlFor="event-count">
                <span>EVENT count</span>
                <select
                  id="event-count"
                  value={eventCount}
                  onChange={(event) => changeEventCount(Number(event.target.value))}
                >
                  {Array.from({ length: config.max_trake_events }, (_, i) => i + 1).map((count) => (
                    <option key={count} value={count}>{count}</option>
                  ))}
                </select>
              </label>

              <div className="event-grid">
                {eventQueries.slice(0, eventCount).map((query, index) => (
                  <label className="event-field" key={index} htmlFor={`event-${index + 1}`}>
                    <div className="event-field__header">
                      <span className="event-field__badge" aria-hidden="true">{index + 1}</span>
                      <span className="event-field__label">EVENT {index + 1}</span>
                    </div>
                    <textarea
                      id={`event-${index + 1}`}
                      aria-label={`EVENT ${index + 1}`}
                      value={query}
                      maxLength={config.max_query_length}
                      onChange={(event) => updateEventQuery(index, event.target.value)}
                      onKeyDown={submitQueryOnEnter}
                      aria-keyshortcuts="Enter Shift+Enter"
                      rows={2}
                    />
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="control-panel">
          <div className="enhance-query-container">
            <label className="toggle-row" htmlFor="enhance-query">
              <span>
                <strong>Enhance query</strong>
              </span>
              <input
                id="enhance-query"
                type="checkbox"
                checked={enhanceQuery}
                disabled={activeType === "KIS" && queryUnderstanding}
                onChange={(event) => setEnhanceQuery(event.target.checked)}
              />
            </label>
          </div>

          <label className="toggle-row" htmlFor="use-reranking">
            <span>
              <strong>Rerank (BLIP-2)</strong>
            </span>
            <input
              id="use-reranking"
              type="checkbox"
              checked={useReranking}
              onChange={(event) => setUseReranking(event.target.checked)}
            />
          </label>

          <fieldset className="source-options embedding-model-options">
            <legend>Embedding Model</legend>
            <label>
              <input
                type="checkbox"
                checked={modelChoices.includes("siglip")}
                onChange={(e) => {
                  if (e.target.checked) {
                    setModelChoices(prev => [...prev, "siglip"]);
                  } else {
                    setModelChoices(prev => prev.filter(m => m !== "siglip"));
                  }
                }}
              />
              SigLIP-2
            </label>
            <label>
              <input
                type="checkbox"
                checked={modelChoices.includes("beit3")}
                onChange={(e) => {
                  if (e.target.checked) {
                    setModelChoices(prev => [...prev, "beit3"]);
                  } else {
                    setModelChoices(prev => prev.filter(m => m !== "beit3"));
                  }
                }}
              />
              BEiT-3
            </label>
          </fieldset>

          <fieldset
            className="source-options"
            disabled={activeType === "KIS" && queryUnderstanding}
          >
            <legend>Sources</legend>
            {SOURCE_OPTIONS.map(({ key, label }) => (
              <label key={key}>
                <input
                  type="checkbox"
                  checked={sources[key]}
                  onChange={(event) =>
                    setSources((current) => ({ ...current, [key]: event.target.checked }))
                  }
                />
                <span>{label}</span>
              </label>
            ))}
          </fieldset>

          {sources.object && (
            <ObjectQueryInput
              terms={objectTerms}
              onChange={setObjectTerms}
              disabled={activeType === "KIS" && queryUnderstanding}
              autoObjects={enhanceQuery}
            />
          )}

          {validationErrors.length > 0 && (
            <div className="form-errors" role="alert">
              <strong>Kiểm tra lại form</strong>
              <ul>
                {validationErrors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </div>
          )}

        </div>
        </form>

        <footer className="workspace__footer">
          <button
            className="search-button"
            type="submit"
            form="search-form"
            disabled={
              planMutation.isPending ||
              (activeType === "KIS" && queryUnderstanding && !kisPlan)
            }
          >
            Search
          </button>
          <input
            id="top-k"
            className="footer-top-k"
            aria-label="Top-K"
            form="search-form"
            type="number"
            min={config.min_top_k}
            max={config.max_top_k}
            step={1}
            value={topK}
            onChange={(event) => setTopK(event.target.value)}
          />
        </footer>
      </aside>

      <div className="sidebar-resizer" onMouseDown={startResizing} aria-hidden="true" title="Drag to resize sidebar" />

      <div className="workspace__results" aria-label="Search results">
        <header
          className={`result-zone__header${
            showProgramFilter ? "" : " result-zone__header--without-program"
          }`}
          aria-label="Result tools"
        >
          <div className="result-zone__header-start">
            {searchMutation.data?.results.length ? (
              searchMutation.data.query_type === "TRAKE" ? (
                <div className="result-zone__summary">
                  <strong>{displayedResultCount} candidates</strong>
                  <span>Temporal candidate rows</span>
                </div>
              ) : (
                <div className="result-group-controls">
                  <label className="result-group-toggle">
                    <input
                      type="checkbox"
                      checked={groupByVideo}
                      onChange={(event) => setGroupByVideo(event.target.checked)}
                    />
                    <span>Group by video</span>
                  </label>
                  {groupByVideo && (
                    <label className="result-group-sort">
                      <span>Sort by</span>
                      <select
                        aria-label="Sort grouped results"
                        value={groupSort}
                        onChange={(event) => setGroupSort(event.target.value as GroupSort)}
                      >
                        <option value="score">Score</option>
                        <option value="time">Time</option>
                      </select>
                    </label>
                  )}
                </div>
              )
            ) : null}
          </div>
          <VideoLookup />
          {showProgramFilter && (
            <label className="program-filter">
              <span>Program</span>
              <select
                aria-label="Program"
                value={programFilter}
                onChange={(event) =>
                  setProgramFilter(event.target.value as ProgramFilter)
                }
              >
                <option value="ALL">ALL</option>
                <option value="L21_L22">HTV 60 Giây</option>
                <option value="L23">Giải đua xe đạp</option>
                <option value="L24">Múa lân</option>
                <option value="L25">Ôn thi THPT</option>
                <option value="L26">Món ngon mỗi ngày</option>
              </select>
            </label>
          )}
          <div className="result-zone__header-end">
            {searchMutation.data?.results.length ? (
              <span className="mini-badge">{searchMutation.data.query_type}</span>
            ) : null}
          </div>
        </header>
        {!searchMutation.isPending && searchMutation.data && (
          <SearchInsight
            response={searchMutation.data}
            payload={searchMutation.variables?.payload}
            objectTerms={objectTerms}
            onPinObject={(term) => {
              setObjectTerms((current) => [...current, term]);
              setSources((current) => ({ ...current, object: true }));
            }}
          />
        )}
        <div className="result-zone__content">
          <SearchState
            mutation={searchMutation}
            maxAnswerLength={config.max_answer_length}
            groupByVideo={groupByVideo}
            groupSort={groupSort}
            programFilter={programFilter}
          />
        </div>
      </div>
    </section>
  );
}

interface SearchStateProps {
  mutation: UseMutationResult<SearchResponse, unknown, SearchMutationVariables>;
  maxAnswerLength: number;
  groupByVideo: boolean;
  groupSort: GroupSort;
  programFilter: ProgramFilter;
}

function SearchState({
  mutation,
  maxAnswerLength,
  groupByVideo,
  groupSort,
  programFilter,
}: SearchStateProps) {
  if (mutation.isPending) {
    return (
      <section className="result-state" aria-live="polite" aria-busy="true">
        <span className="spinner" aria-hidden="true" />
        <div>
          <strong>Đang tìm kiếm…</strong>
          <p>Request trước đã được hủy nếu vẫn đang chạy.</p>
        </div>
      </section>
    );
  }

  if (mutation.isError) {
    return (
      <section className="result-state result-state--error" role="alert">
        <strong>Tìm kiếm không thành công</strong>
        <p>{friendlySearchError(mutation.error)}</p>
      </section>
    );
  }

  if (!mutation.data) {
    return (
      <section className="result-state result-state--idle">
        <strong>Chưa có kết quả</strong>
        <p>Kết quả sẽ xuất hiện tại đây sau khi tìm kiếm.</p>
      </section>
    );
  }

  if (mutation.data.results.length === 0) {
    return (
      <section className="result-state result-state--empty" role="status">
        <strong>Không tìm thấy candidate</strong>
        <p>Thử mô tả khác hoặc bật thêm nguồn tìm kiếm.</p>
      </section>
    );
  }

  const displayedResults = mutation.data.results.filter(
    (result) => matchesProgram(result.video_id, programFilter),
  );

  if (displayedResults.length === 0) {
    return (
      <section className="result-state result-state--empty" role="status">
        <strong>Không có kết quả thuộc chương trình đã chọn</strong>
        <p>Chọn ALL hoặc một chương trình khác để xem kết quả.</p>
      </section>
    );
  }

  const displayedResponse = { ...mutation.data, results: displayedResults } as SearchResponse;

  const submittedTrakeEventCount =
    mutation.variables?.payload.query_type === "TRAKE"
      ? mutation.variables.payload.events.length
      : null;

  return (
    <section className="result-preview" aria-live="polite">
      {displayedResponse.query_type === "TRAKE" ? (
        submittedTrakeEventCount === null ? (
          <section className="trake-validation-error" role="alert">
            <strong>Cannot display TRAKE results</strong>
            <p>The submitted EVENT count is unavailable for response validation.</p>
          </section>
        ) : (
          <TrakeResultInspector
            response={displayedResponse}
            expectedEventCount={submittedTrakeEventCount}
          />
        )
      ) : (
        <SingleResultInspector
          response={displayedResponse}
          maxAnswerLength={maxAnswerLength}
          groupByVideo={groupByVideo}
          groupSort={groupSort}
        />
      )}
    </section>
  );
}
