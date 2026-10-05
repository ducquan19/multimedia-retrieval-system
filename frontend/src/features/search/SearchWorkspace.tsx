import {
  type ClipboardEvent,
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
  type TrafficFilters,
} from "../../api/types";
import { SingleResultInspector } from "../results/SingleResultInspector";
import { TrakeResultInspector } from "../results/TrakeResultInspector";
import { VideoLookup } from "../results/VideoLookup";
import { SubmissionLogButton } from "../submission/SubmissionLogButton";
import { ObjectQueryInput } from "./ObjectQueryInput";
import { type QueryHistoryEntry, QueryHistorySelect, useQueryHistory } from "./QueryHistory";
import { SearchInsight } from "./SearchInsight";
import { EMPTY_TRAFFIC_FILTERS, TrafficFilterPanel } from "./TrafficFilterPanel";
import { matchesProgram, type ProgramFilter, programOptions } from "./programFilter";
import { buildSearchRequest, queryLengthError } from "./searchPayload";
import { parseTrakeEvents } from "./trakeEventParser";
import { useResizableSidebar } from "./useResizableSidebar";
import { useThemePreference } from "./useThemePreference";

const SOURCE_OPTIONS: { key: keyof SearchSources; label: string }[] = [
  { key: "image", label: "Ảnh" },
  { key: "asr", label: "ASR" },
  { key: "object", label: "Object" },
];

type GroupSort = "score" | "time";

interface SearchMutationVariables {
  payload: SearchRequest;
  signal: AbortSignal;
}

interface SearchWorkspaceProps {
  config: PublicConfig;
}


export function SearchWorkspace({ config }: SearchWorkspaceProps) {
  const [isDarkMode, setIsDarkMode] = useThemePreference();
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
  const [groupByVideo, setGroupByVideo] = useState(false);
  const [groupSort, setGroupSort] = useState<GroupSort>("score");
  const [programFilter, setProgramFilter] = useState<ProgramFilter>("ALL");
  const activeController = useRef<AbortController | null>(null);
  const queryHistory = useQueryHistory();

  const sidebar = useResizableSidebar();

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
      sidebar.widenTo(550);
    },
  });
  const displayedResultCount =
    searchMutation.data?.results.filter((result) =>
      matchesProgram(result.video_id, programFilter),
    ).length ?? 0;
  const resultProgramOptions = programOptions(
    searchMutation.data?.results.map((result) => result.video_id) ?? [],
    programFilter,
  );
  const showProgramFilter =
    !searchMutation.isPending &&
    Boolean(searchMutation.data?.results.length) &&
    searchMutation.data?.query_type !== "TRAFFIC";

  useEffect(
    () => () => {
      activeController.current?.abort();
    },
    [],
  );

  const changeTab = (queryType: QueryType) => {
    activeController.current?.abort();
    searchMutation.reset();
    planMutation.reset();
    setValidationErrors([]);
    setActiveType(queryType);
    if (queryType !== "KIS") {
      sidebar.restoreNormal();
    } else if (queryUnderstanding) {
      sidebar.widenTo(550);
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
    if (enabled) {
      setEnhanceQuery(false);
      sidebar.widenTo(550);
    } else {
      sidebar.restoreNormal();
    }
  };

  const understandKisQuery = () => {
    const queryError = queryLengthError("Truy vấn KIS", kisQuery, config.max_query_length);
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
    const { payload, errors } = buildSearchRequest(
      {
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
      },
      config,
    );
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
    queryHistory.record(
      payload.query_type === "TRAKE"
        ? {
            type: "TRAKE",
            at: Date.now(),
            mainQuery: payload.main_query ?? "",
            events: payload.events.map((event) => event.query),
          }
        : {
            type: payload.query_type === "TRAFFIC" ? "TRAFFIC" : "KIS",
            at: Date.now(),
            query: payload.query,
          },
    );
  };

  const restoreQuery = (entry: QueryHistoryEntry) => {
    setValidationErrors([]);
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

  const planned = activeType === "KIS" && queryUnderstanding;
  const response = searchMutation.data;
  const toggleModel = (model: "siglip" | "beit3", enabled: boolean) =>
    setModelChoices((current) =>
      enabled ? [...current, model] : current.filter((item) => item !== model),
    );

  return (
    <section className="workspace" aria-label="Retrieval workspace">
      <aside
        className="rail"
        aria-label="Truy vấn"
        style={{
          width: sidebar.width,
          transition: sidebar.isResizing ? "none" : undefined,
        }}
      >
        <header className="rail__brand">
          <h1>
            Retrieval Inspector <span>AIC 2026</span>
          </h1>
          <label className="theme-switch" title="Chế độ tối">
            <input
              type="checkbox"
              role="switch"
              aria-label="Chế độ tối"
              checked={isDarkMode}
              onChange={(event) => setIsDarkMode(event.target.checked)}
            />
            <span className="theme-switch__track" aria-hidden="true" />
          </label>
        </header>

        <div className="query-tabs" role="tablist" aria-label="Loại truy vấn">
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
              {queryType}
            </button>
          ))}
        </div>

        <form id="search-form" className="rail__form" onSubmit={submitSearch} noValidate>
          <div
            id={`panel-${activeType}`}
            role="tabpanel"
            aria-labelledby={`tab-${activeType}`}
            className="rail__section rail__query"
          >
            <QueryHistorySelect
              type={activeType}
              entries={queryHistory.entries}
              onRestore={restoreQuery}
            />

            {activeType === "KIS" && (
              <>
                <label className="field" htmlFor="kis-query">
                  <span className="field__label">Truy vấn KIS</span>
                  <textarea
                    id="kis-query"
                    className="field__query"
                    value={kisQuery}
                    maxLength={config.max_query_length}
                    onChange={(event) => changeKisQuery(event.target.value)}
                    onKeyDown={submitQueryOnEnter}
                    aria-keyshortcuts="Enter Shift+Enter"
                    placeholder="Mô tả khoảnh khắc cần tìm, ví dụ: người đàn ông áo đỏ phát biểu trước micro"
                    rows={5}
                  />
                </label>

                <div className="plan">
                  <div className="plan__head">
                    <label className="switch-row" htmlFor="query-understanding">
                      <span>
                        Lập kế hoạch nhiều sự kiện
                        <small id="query-understanding-hint">Gemini tách truy vấn thành các mốc để bạn sửa trước khi tìm</small>
                      </span>
                      <input
                        id="query-understanding"
                        type="checkbox"
                        role="switch"
                        aria-label="Lập kế hoạch nhiều sự kiện"
                        aria-describedby="query-understanding-hint"
                        checked={queryUnderstanding}
                        onChange={(event) => toggleQueryUnderstanding(event.target.checked)}
                      />
                    </label>
                    {queryUnderstanding && (
                      <button
                        type="button"
                        className="button button--quiet"
                        onClick={understandKisQuery}
                        disabled={planMutation.isPending}
                      >
                        {planMutation.isPending ? "Đang phân tích…" : "Phân tích truy vấn"}
                      </button>
                    )}
                  </div>

                  {queryUnderstanding && planMutation.isError && (
                    <p className="notice notice--error" role="alert">
                      {friendlySearchError(planMutation.error)}
                    </p>
                  )}

                  {queryUnderstanding && kisPlan && (
                    <section className="plan__body" aria-label="Kế hoạch truy vấn KIS">
                      <label className="field field--inline" htmlFor="kis-search-mode">
                        <span className="field__label">Chiến lược</span>
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
                          <option value="single_anchor">Một mốc chính</option>
                          <option value="multi_anchor">Nhiều mốc, không theo thứ tự</option>
                          <option value="temporal_sequence">Theo thứ tự thời gian</option>
                        </select>
                      </label>

                      <ol className="plan__events">
                        {kisPlan.events.map((planEvent, index) => (
                          <li className="plan-event" key={planEvent.event_index}>
                            <header className="plan-event__head">
                              <span className="sequence-mark" aria-hidden="true">
                                E{planEvent.event_index}
                              </span>
                              <strong>EVENT {planEvent.event_index}</strong>
                              <span className="plan-event__confidence">
                                {Math.round(planEvent.confidence * 100)}% tin cậy
                              </span>
                              <button
                                type="button"
                                className="button button--text"
                                onClick={() => removePlanEvent(index)}
                                disabled={kisPlan.events.length === 1}
                                aria-label={`Xoá EVENT ${planEvent.event_index}`}
                              >
                                Xoá
                              </button>
                            </header>
                            <p className="plan-event__source">{planEvent.source_span_vi}</p>
                            <label className="field">
                              <span className="field__label">Hình ảnh (tiếng Anh)</span>
                              <textarea
                                aria-label={`Truy vấn hình ảnh EVENT ${planEvent.event_index}`}
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
                              <span className="field__label">Lời thoại ASR (tiếng Việt)</span>
                              <textarea
                                aria-label={`Truy vấn ASR EVENT ${planEvent.event_index}`}
                                value={planEvent.asr_query_vi ?? ""}
                                onChange={(event) =>
                                  updatePlanEvent(index, {
                                    asr_query_vi: event.target.value || null,
                                  })
                                }
                                rows={2}
                              />
                            </label>
                            <label className="field field--inline">
                              <span className="field__label">Vai trò</span>
                              <select
                                aria-label={`Vai trò EVENT ${planEvent.event_index}`}
                                value={planEvent.importance}
                                onChange={(event) =>
                                  updatePlanEvent(index, {
                                    importance: event.target
                                      .value as KISQueryPlanEvent["importance"],
                                  })
                                }
                              >
                                <option value="anchor">Mốc chính</option>
                                <option value="supporting">Hỗ trợ</option>
                                <option value="context">Bối cảnh</option>
                              </select>
                            </label>
                            {planEvent.inferred && (
                              <p className="notice notice--warning">
                                Có suy luận ngoài câu gốc. Kiểm tra trước khi tìm.
                              </p>
                            )}
                          </li>
                        ))}
                      </ol>

                      {kisPlan.warnings.map((warning) => (
                        <p className="notice notice--warning" key={warning}>
                          {warning}
                        </p>
                      ))}
                    </section>
                  )}
                </div>
              </>
            )}

            {activeType === "TRAFFIC" && (
              <>
                <label className="field" htmlFor="traffic-query">
                  <span className="field__label">Truy vấn TRAFFIC</span>
                  <textarea
                    id="traffic-query"
                    className="field__query"
                    value={trafficQuery}
                    maxLength={config.max_query_length}
                    onChange={(event) => setTrafficQuery(event.target.value)}
                    onKeyDown={submitQueryOnEnter}
                    aria-keyshortcuts="Enter Shift+Enter"
                    placeholder="Mô tả xe, người, màu sắc, vị trí. Tên đường, giờ và thời tiết chọn ở bộ lọc bên dưới."
                    rows={4}
                  />
                </label>
                <TrafficFilterPanel filters={trafficFilters} onChange={setTrafficFilters} />
              </>
            )}

            {activeType === "TRAKE" && (
              <>
                <label className="field" htmlFor="trake-main-query">
                  <span className="field__label">Truy vấn chính</span>
                  <textarea
                    id="trake-main-query"
                    value={trakeMainQuery}
                    maxLength={config.max_query_length}
                    onChange={(event) => setTrakeMainQuery(event.target.value)}
                    onKeyDown={submitQueryOnEnter}
                    onPaste={pasteTrakeEvents}
                    aria-keyshortcuts="Enter Shift+Enter"
                    placeholder={"Dán cả đề bài để tự tách EVENT:\nE1: …\nE2: …\nE3: …"}
                    rows={3}
                  />
                </label>

                <label className="field field--inline" htmlFor="event-count">
                  <span className="field__label">Số EVENT</span>
                  <select
                    id="event-count"
                    value={eventCount}
                    onChange={(event) => changeEventCount(Number(event.target.value))}
                  >
                    {Array.from({ length: config.max_trake_events }, (_, i) => i + 1).map(
                      (count) => (
                        <option key={count} value={count}>
                          {count}
                        </option>
                      ),
                    )}
                  </select>
                </label>

                <ol className="trake-events">
                  {eventQueries.slice(0, eventCount).map((query, index) => (
                    <li key={index}>
                      <label className="trake-event" htmlFor={`event-${index + 1}`}>
                        <span className="sequence-mark" aria-hidden="true">
                          E{index + 1}
                        </span>
                        <textarea
                          id={`event-${index + 1}`}
                          aria-label={`EVENT ${index + 1}`}
                          value={query}
                          maxLength={config.max_query_length}
                          onChange={(event) => updateEventQuery(index, event.target.value)}
                          onKeyDown={submitQueryOnEnter}
                          onPaste={pasteTrakeEvents}
                          aria-keyshortcuts="Enter Shift+Enter"
                          placeholder={`Sự kiện ${index + 1}`}
                          rows={2}
                        />
                      </label>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </div>

          <div className="rail__section">
            <fieldset className="chip-group" disabled={planned}>
              <legend>Nguồn</legend>
              {SOURCE_OPTIONS.filter(
                ({ key }) => !(activeType === "TRAFFIC" && key === "asr"),
              ).map(({ key, label }) => (
                <label className="chip" key={key}>
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
                disabled={planned}
                autoObjects={enhanceQuery}
              />
            )}

            <fieldset className="chip-group">
              <legend>Model ảnh</legend>
              <label className="chip">
                <input
                  type="checkbox"
                  checked={modelChoices.includes("siglip")}
                  onChange={(event) => toggleModel("siglip", event.target.checked)}
                />
                <span>SigLIP-2</span>
              </label>
              <label className="chip">
                <input
                  type="checkbox"
                  checked={modelChoices.includes("beit3")}
                  onChange={(event) => toggleModel("beit3", event.target.checked)}
                />
                <span>BEiT-3</span>
              </label>
            </fieldset>
          </div>

          <div className="rail__section rail__switches">
            <label className="switch-row" htmlFor="enhance-query">
              <span>
                Enhance query
                <small id="enhance-query-hint">Gemini viết lại truy vấn, chọn object và trọng số từng nguồn</small>
              </span>
              <input
                id="enhance-query"
                type="checkbox"
                role="switch"
                aria-label="Enhance query"
                aria-describedby="enhance-query-hint"
                checked={enhanceQuery}
                disabled={planned}
                onChange={(event) => setEnhanceQuery(event.target.checked)}
              />
            </label>
            <label className="switch-row" htmlFor="use-reranking">
              <span>
                Rerank BLIP-2
                <small id="use-reranking-hint">Chấm lại các kết quả đầu, chậm hơn</small>
              </span>
              <input
                id="use-reranking"
                type="checkbox"
                role="switch"
                aria-label="Rerank BLIP-2"
                aria-describedby="use-reranking-hint"
                checked={useReranking}
                onChange={(event) => setUseReranking(event.target.checked)}
              />
            </label>
            {activeType === "KIS" && (
              <label className="switch-row" htmlFor="include-traffic">
                <span>Gồm video giao thông (N)</span>
                <input
                  id="include-traffic"
                  type="checkbox"
                  role="switch"
                  checked={includeTraffic}
                  onChange={(event) => setIncludeTraffic(event.target.checked)}
                />
              </label>
            )}
          </div>

          {validationErrors.length > 0 && (
            <div className="notice notice--error rail__errors" role="alert">
              <strong>Chưa tìm được</strong>
              <ul>
                {validationErrors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </div>
          )}
        </form>

        <footer className="rail__footer">
          <label className="top-k" htmlFor="top-k">
            <span>Top-K</span>
            <input
              id="top-k"
              aria-label="Top-K"
              form="search-form"
              type="number"
              min={config.min_top_k}
              max={config.max_top_k}
              step={1}
              value={topK}
              onChange={(event) => setTopK(event.target.value)}
            />
          </label>
          <button
            className="button button--primary rail__search"
            type="submit"
            form="search-form"
            disabled={planMutation.isPending || (planned && !kisPlan)}
          >
            Tìm kiếm
          </button>
        </footer>
      </aside>

      <div
        className="rail-resizer"
        onMouseDown={(event) => sidebar.startResizing(event, !planned)}
        aria-hidden="true"
        title="Kéo để đổi độ rộng"
      />

      <div className="sheet" aria-label="Kết quả tìm kiếm">
        <header className="toolbar" aria-label="Công cụ kết quả">
          <div className="toolbar__group">
            {response?.results.length && !searchMutation.isPending ? (
              <p className="toolbar__count">
                <strong>{displayedResultCount}</strong>{" "}
                {response.query_type === "TRAKE" ? "chuỗi ứng viên" : "kết quả"}
                {response.query_type === "TRAFFIC" && (
                  <span>
                    {" "}
                    trong {response.filtered_keyframes.toLocaleString("vi-VN")} keyframe qua bộ lọc
                  </span>
                )}
              </p>
            ) : null}
            {response?.results.length &&
            !searchMutation.isPending &&
            response.query_type !== "TRAKE" ? (
              <>
                <label className="chip chip--small">
                  <input
                    type="checkbox"
                    checked={groupByVideo}
                    onChange={(event) => setGroupByVideo(event.target.checked)}
                  />
                  <span>Gộp theo video</span>
                </label>
                {groupByVideo && (
                  <select
                    className="select--small"
                    aria-label="Sắp xếp trong nhóm"
                    value={groupSort}
                    onChange={(event) => setGroupSort(event.target.value as GroupSort)}
                  >
                    <option value="score">Theo điểm</option>
                    <option value="time">Theo thời gian</option>
                  </select>
                )}
              </>
            ) : null}
            {showProgramFilter && (
              <select
                className="select--small"
                aria-label="Chương trình"
                value={programFilter}
                onChange={(event) => setProgramFilter(event.target.value)}
              >
                <option value="ALL">Mọi chương trình</option>
                {resultProgramOptions.map(({ key, label }) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="toolbar__group toolbar__group--end">
            <VideoLookup />
            <SubmissionLogButton />
          </div>
        </header>

        {!searchMutation.isPending && response && (
          <SearchInsight
            response={response}
            payload={searchMutation.variables?.payload}
            objectTerms={objectTerms}
            onPinObject={(term) => {
              setObjectTerms((current) => [...current, term]);
              setSources((current) => ({ ...current, object: true }));
            }}
          />
        )}
        <div className="sheet__content">
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
      <section className="sheet-state" aria-live="polite" aria-busy="true">
        <span className="spinner" aria-hidden="true" />
        <strong>Đang tìm kiếm…</strong>
      </section>
    );
  }

  if (mutation.isError) {
    return (
      <section className="sheet-state sheet-state--error" role="alert">
        <strong>Tìm kiếm không thành công</strong>
        <p>{friendlySearchError(mutation.error)}</p>
      </section>
    );
  }

  if (!mutation.data) {
    return (
      <section className="sheet-state">
        <strong>Chưa có kết quả</strong>
        <p>Nhập truy vấn ở cột trái rồi nhấn Enter. Kết quả hiện ở đây theo thứ hạng.</p>
      </section>
    );
  }

  if (mutation.data.results.length === 0) {
    return (
      <section className="sheet-state" role="status">
        <strong>Không tìm thấy kết quả</strong>
        <p>Thử mô tả theo cách khác hoặc bật thêm nguồn tìm kiếm.</p>
      </section>
    );
  }

  const displayedResults = mutation.data.results.filter((result) =>
    matchesProgram(result.video_id, programFilter),
  );

  if (displayedResults.length === 0) {
    return (
      <section className="sheet-state" role="status">
        <strong>Không có kết quả thuộc chương trình đã chọn</strong>
        <p>Chọn Mọi chương trình để xem lại toàn bộ kết quả.</p>
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
          <section className="sheet-state sheet-state--error" role="alert">
            <strong>Không hiển thị được kết quả TRAKE</strong>
            <p>Thiếu số EVENT đã gửi để kiểm tra phản hồi.</p>
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
