import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { type UseMutationResult, useMutation } from "@tanstack/react-query";

import { friendlySearchError, search } from "../../api/client";
import {
  QUERY_TYPES,
  type PublicConfig,
  type QueryType,
  type SearchRequest,
  type SearchResponse,
  type SearchSources,
} from "../../api/types";
import { SingleResultInspector } from "../results/SingleResultInspector";
import { TrakeResultInspector } from "../results/TrakeResultInspector";

const SOURCE_OPTIONS: { key: keyof SearchSources; label: string }[] = [
  { key: "image", label: "Image" },
  { key: "asr", label: "ASR" },
  { key: "object", label: "Object" },
  { key: "ocr", label: "OCR" },
];

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
  const [activeType, setActiveType] = useState<QueryType>("KIS");
  const [topK, setTopK] = useState(String(config.default_top_k));
  const [enhanceQuery, setEnhanceQuery] = useState(false);
  const [useReranking, setUseReranking] = useState(false);
  const [sources, setSources] = useState<SearchSources>({
    image: true,
    asr: false,
    ocr: false,
    object: false,
  });
  const [modelChoices, setModelChoices] = useState<Array<"siglip" | "beit3">>(["siglip", "beit3"]);
  const [kisQuery, setKisQuery] = useState("");
  const [vqaQuery, setVqaQuery] = useState("");
  const [trakeMainQuery, setTrakeMainQuery] = useState("");
  const initialEventCount = Math.min(4, config.max_trake_events);
  const [eventCount, setEventCount] = useState(initialEventCount);
  const [eventQueries, setEventQueries] = useState<string[]>(() =>
    Array.from({ length: initialEventCount }, () => ""),
  );
  const [validationErrors, setValidationErrors] = useState<string[]>([]);
  const activeController = useRef<AbortController | null>(null);

  const searchMutation = useMutation<SearchResponse, unknown, SearchMutationVariables>({
    mutationFn: ({ payload, signal }) => search(payload, signal),
  });

  useEffect(
    () => () => {
      activeController.current?.abort();
    },
    [],
  );

  const changeTab = (queryType: QueryType) => {
    activeController.current?.abort();
    searchMutation.reset();
    setValidationErrors([]);
    setActiveType(queryType);
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

  const buildPayload = (): SearchRequest | null => {
    const errors: string[] = [];
    const parsedTopK = Number(topK);
    if (!Number.isInteger(parsedTopK) || parsedTopK < 1 || parsedTopK > 100) {
      errors.push("Top-K phải là số nguyên từ 1 đến 100.");
    }
    if (!Object.values(sources).some(Boolean)) {
      errors.push("Chọn ít nhất một nguồn tìm kiếm.");
    }
    if (modelChoices.length === 0) {
      errors.push("Chọn ít nhất một model.");
    }

    const common = {
      top_k: parsedTopK,
      enhance_query: enhanceQuery,
      use_reranking: useReranking,
      search_sources: sources,
      model_choices: modelChoices,
    };

    let payload: SearchRequest;
    if (activeType === "KIS") {
      const queryError = queryLengthError("Query KIS", kisQuery, config.max_query_length);
      if (queryError) errors.push(queryError);
      payload = { query_type: "KIS", query: kisQuery.trim(), ...common };
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
          `Event ${index + 1}`,
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
      <aside className="workspace__sidebar" aria-label="Query controls">
        <header className="workspace__brand">AIC Retrieval Inspector</header>

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
            <label className="field field--query-only" htmlFor="kis-query">
              <span>Query KIS</span>
              <textarea
                id="kis-query"
                value={kisQuery}
                maxLength={config.max_query_length}
                onChange={(event) => setKisQuery(event.target.value)}
                onKeyDown={submitQueryOnEnter}
                aria-keyshortcuts="Enter Shift+Enter"
                placeholder="Ví dụ: một người mở laptop trên bàn"
                rows={6}
              />
            </label>
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
                placeholder="Ví dụ: chiếc ly người phụ nữ đang cầm có màu gì?"
                rows={6}
              />
            </label>
          )}

          {activeType === "TRAKE" && (
            <div className="trake-fields">
              <label className="field" htmlFor="trake-main-query">
                <span>Main query TRAKE</span>
                <small>Mô tả toàn bộ chuỗi sự kiện theo trình tự thời gian.</small>
                <textarea
                  id="trake-main-query"
                  value={trakeMainQuery}
                  maxLength={config.max_query_length}
                  onChange={(event) => setTrakeMainQuery(event.target.value)}
                  onKeyDown={submitQueryOnEnter}
                  aria-keyshortcuts="Enter Shift+Enter"
                  rows={4}
                />
              </label>

              <label className="top-k-row" htmlFor="event-count">
                <span>Event count</span>
                <select
                  id="event-count"
                  value={eventCount}
                  onChange={(event) => changeEventCount(Number(event.target.value))}
                  style={{ width: "6rem", padding: "0.45rem 0.6rem" }}
                >
                  {Array.from({ length: config.max_trake_events }, (_, index) => index + 1).map(
                    (count) => (
                      <option key={count} value={count}>
                        {count}
                      </option>
                    ),
                  )}
                </select>
              </label>

              <div className="event-grid">
                {eventQueries.slice(0, eventCount).map((query, index) => (
                  <label className="field event-field" key={index} htmlFor={`event-${index + 1}`}>
                    <span>Event {index + 1}</span>
                    <textarea
                      id={`event-${index + 1}`}
                      value={query}
                      maxLength={config.max_query_length}
                      onChange={(event) => updateEventQuery(index, event.target.value)}
                      onKeyDown={submitQueryOnEnter}
                      aria-keyshortcuts="Enter Shift+Enter"
                      rows={3}
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
                onChange={(event) => setEnhanceQuery(event.target.checked)}
              />
            </label>
            
            {searchMutation.data?.warnings?.length ? (
              <div className="sidebar-warning">
                <small><strong>Warning</strong></small>
                {searchMutation.data.warnings.map((w, i) => <p key={i}>⚠️ {w}</p>)}
              </div>
            ) : null}

            {searchMutation.data?.enhanced_query && (
              <div className="sidebar-enhanced-query">
                <small><strong>Enhanced:</strong></small>
                <p>{searchMutation.data.enhanced_query.replace("- ", "")}</p>
              </div>
            )}
            
            {searchMutation.data?.applied_weights && (
              <div className="sidebar-weights">
                <small><strong>Weights Applied:</strong></small>
                <p>
                  <span>VIS: {searchMutation.data.applied_weights.w_vis.toFixed(2)}</span>
                  <span>OCR: {searchMutation.data.applied_weights.w_ocr.toFixed(2)}</span>
                  <span>ASR: {searchMutation.data.applied_weights.w_asr.toFixed(2)}</span>
                </p>
              </div>
            )}
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

          <fieldset className="source-options">
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

          <fieldset className="source-options">
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
          <button className="search-button" type="submit" form="search-form">
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

      <div className="workspace__results" aria-label="Search results">
        <SearchState mutation={searchMutation} maxAnswerLength={config.max_answer_length} />
      </div>
    </section>
  );
}

interface SearchStateProps {
  mutation: UseMutationResult<SearchResponse, unknown, SearchMutationVariables>;
  maxAnswerLength: number;
}

function SearchState({ mutation, maxAnswerLength }: SearchStateProps) {
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

  const submittedTrakeEventCount =
    mutation.variables?.payload.query_type === "TRAKE"
      ? mutation.variables.payload.events.length
      : null;

  return (
    <section className="result-preview" aria-live="polite">
      {mutation.data.query_type === "TRAKE" ? (
        submittedTrakeEventCount === null ? (
          <section className="trake-validation-error" role="alert">
            <strong>Cannot display TRAKE results</strong>
            <p>The submitted event count is unavailable for response validation.</p>
          </section>
        ) : (
          <TrakeResultInspector
            response={mutation.data}
            expectedEventCount={submittedTrakeEventCount}
          />
        )
      ) : (
        <SingleResultInspector response={mutation.data} maxAnswerLength={maxAnswerLength} />
      )}
    </section>
  );
}
