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
  type TopK,
} from "../../api/types";
import { SingleResultInspector } from "../results/SingleResultInspector";

const QUERY_TYPE_LABELS: Record<QueryType, string> = {
  KIS: "Known Item Search",
  VQA: "Visual Question Answering",
  TRAKE: "Temporal event search",
};

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
  const [topK, setTopK] = useState<TopK>(config.default_top_k);
  const [enhanceQuery, setEnhanceQuery] = useState(false);
  const [sources, setSources] = useState<SearchSources>({
    image: true,
    asr: false,
    object: false,
    ocr: false,
  });
  const [kisQuery, setKisQuery] = useState("");
  const [vqaQuery, setVqaQuery] = useState("");
  const [trakeMainQuery, setTrakeMainQuery] = useState("");
  const initialEventCount = Math.min(2, config.max_trake_events);
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
    if (!Object.values(sources).some(Boolean)) {
      errors.push("Chọn ít nhất một nguồn tìm kiếm.");
    }

    const common = {
      top_k: topK,
      enhance_query: enhanceQuery,
      search_sources: sources,
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
      const mainQueryError = queryLengthError(
        "Main query TRAKE",
        trakeMainQuery,
        config.max_query_length,
      );
      if (mainQueryError) errors.push(mainQueryError);
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
        main_query: trakeMainQuery.trim(),
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
    <section className="workspace" aria-labelledby="workspace-heading">
      <div className="workspace__intro">
        <div>
          <p className="eyebrow eyebrow--dark">Query workspace</p>
          <h2 id="workspace-heading">Inspect retrieval candidates</h2>
          <p>Chọn loại truy vấn, cấu hình nguồn tìm kiếm và gửi tới mock API.</p>
        </div>
        <div className="mode-note">
          <span className="mode-note__dot" aria-hidden="true" />
          Fixture data · no AI inference
        </div>
      </div>

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
            <span>{QUERY_TYPE_LABELS[queryType]}</span>
          </button>
        ))}
      </div>

      <form className="search-layout" onSubmit={submitSearch} noValidate>
        <div
          id={`panel-${activeType}`}
          role="tabpanel"
          aria-labelledby={`tab-${activeType}`}
          className="query-panel"
        >
          {activeType === "KIS" && (
            <label className="field" htmlFor="kis-query">
              <span>Query KIS</span>
              <small>Mô tả khoảnh khắc hoặc sự kiện cần tìm.</small>
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
            <label className="field" htmlFor="vqa-query">
              <span>Câu hỏi VQA</span>
              <small>Ứng dụng chỉ tìm keyframe; câu trả lời không được tự động tạo.</small>
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

              <label className="field field--compact" htmlFor="event-count">
                <span>Event count</span>
                <select
                  id="event-count"
                  value={eventCount}
                  onChange={(event) => changeEventCount(Number(event.target.value))}
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

        <aside className="control-panel" aria-label="Search controls">
          <label className="field field--compact" htmlFor="top-k">
            <span>Top K</span>
            <select
              id="top-k"
              value={topK}
              onChange={(event) => setTopK(Number(event.target.value) as TopK)}
            >
              {config.top_k_options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <button className="search-button" type="submit">
            {searchMutation.isPending ? `Search ${activeType} again` : `Search ${activeType}`}
          </button>
          <p className="query-shortcut-hint">
            <kbd>Enter</kbd> Search <span aria-hidden="true">·</span> <kbd>Shift+Enter</kbd> New line
          </p>

          <label className="toggle-row" htmlFor="enhance-query">
            <span>
              <strong>Enhance query</strong>
              <small>Mock Gemini enhancement</small>
            </span>
            <input
              id="enhance-query"
              type="checkbox"
              checked={enhanceQuery}
              onChange={(event) => setEnhanceQuery(event.target.checked)}
            />
          </label>

          <fieldset className="source-options">
            <legend>Search sources</legend>
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

        </aside>
      </form>

      <SearchState mutation={searchMutation} maxAnswerLength={config.max_answer_length} />
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
          <strong>Đang tìm trong fixture…</strong>
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
        <p>Kết quả từ API sẽ xuất hiện tại đây sau khi tìm kiếm.</p>
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

  return (
    <section className="result-preview" aria-live="polite">
      {mutation.data.enhanced_query && (
        <div className="enhanced-callout" aria-label="Enhanced query">
          <div className="enhanced-callout__heading">
            <strong>Query enhancement</strong>
            <span className="mini-badge">Mock</span>
          </div>
          <dl>
            <div>
              <dt>Original</dt>
              <dd>{mutation.data.original_query}</dd>
            </div>
            <div>
              <dt>Enhanced</dt>
              <dd>{mutation.data.enhanced_query}</dd>
            </div>
          </dl>
        </div>
      )}

      {mutation.data.query_type === "TRAKE" ? (
        <>
          <div className="result-preview__heading">
            <div>
              <p className="eyebrow eyebrow--dark">API response</p>
              <h3>{mutation.data.results.length} candidates received</h3>
            </div>
            <span className="mini-badge">TRAKE</span>
          </div>
          <ol className="result-list" aria-label="Retrieved candidates">
            {mutation.data.results.map((result) => (
              <li key={result.result_id}>
                <span>#{result.rank}</span>
                <strong>{result.video_id}</strong>
                <small>{result.result_id}</small>
              </li>
            ))}
          </ol>
          <p className="phase-note">TRAKE row inspector sẽ được bổ sung ở Phase 6.</p>
        </>
      ) : (
        <SingleResultInspector response={mutation.data} maxAnswerLength={maxAnswerLength} />
      )}
    </section>
  );
}
