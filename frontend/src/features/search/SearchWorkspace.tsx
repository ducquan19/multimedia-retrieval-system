import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { search, searchSimilar } from "../../api/client";
import {
  QUERY_TYPES,
  type PublicConfig,
  type QueryType,
  type SearchRequest,
  type SearchResponse,
  type SimilarSearchRequest,
  type SimilarSearchResponse,
} from "../../api/types";
import { useResultViewPreferences } from "../results/useResultViewPreferences";
import { AutoGrowTextarea } from "../../shared/AutoGrowTextarea";
import { KisQueryFields } from "./KisQueryFields";
import { type QueryHistoryEntry, QueryHistorySelect, useQueryHistory } from "./QueryHistory";
import { ResultsToolbar } from "./ResultsToolbar";
import { SearchInsight } from "./SearchInsight";
import { SearchOptionsPanel } from "./SearchOptionsPanel";
import { ShortcutsHelp } from "./ShortcutsHelp";
import { type GroupSort, SearchResultsView } from "./SearchResultsView";
import { TrafficFilterPanel } from "./TrafficFilterPanel";
import { TrakeQueryFields } from "./TrakeQueryFields";
import type { ProgramFilter } from "./programFilter";
import { type CachedSearch, SearchResultCache } from "./searchCache";
import { formFromRequest } from "./searchPayload";
import { submitOnEnter } from "./submitOnEnter";
import { useResizableSidebar } from "./useResizableSidebar";
import { useSearchForm } from "./useSearchForm";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { useThemePreference } from "./useThemePreference";

const PLAN_EDITOR_WIDTH = 550;

interface SearchMutationVariables {
  payload: SearchRequest;
  signal: AbortSignal;
}

interface SearchWorkspaceProps {
  config: PublicConfig;
}

/** Keyframes that look like an example, shown instead of the text search results. */
interface SimilarResults {
  request: SimilarSearchRequest;
  response: SimilarSearchResponse;
  elapsedMs: number;
}

const QUERY_FIELD_IDS: Record<QueryType, string> = {
  KIS: "kis-query",
  TRAFFIC: "traffic-query",
  TRAKE: "trake-main-query",
};

function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

/**
 * The search screen: the query rail on the left, the result sheet on the right.
 *
 * The form itself lives in useSearchForm; this component runs searches, keeps the results of
 * this page session and the query history, and lays the parts out.
 */
export function SearchWorkspace({ config }: SearchWorkspaceProps) {
  const [themeMode, setThemeMode] = useThemePreference();
  const activeController = useRef<AbortController | null>(null);
  /** Cancel the running search or plan request and start a new one. */
  const nextSignal = () => {
    activeController.current?.abort();
    const controller = new AbortController();
    activeController.current = controller;
    return controller.signal;
  };
  const form = useSearchForm(config, nextSignal);
  const { activeType, queryUnderstanding, kisPlan } = form.state;

  const [groupByVideo, setGroupByVideo] = useState(false);
  const [groupSort, setGroupSort] = useState<GroupSort>("score");
  const [programFilter, setProgramFilter] = useState<ProgramFilter>("ALL");
  const queryHistory = useQueryHistory();
  // Results of this page session's searches, so a query picked from the history shows at once.
  const [resultCache] = useState(() => new SearchResultCache(30));
  const [shown, setShown] = useState<
    (CachedSearch & { fromCache: boolean; elapsedMs: number | null }) | null
  >(null);
  const [similar, setSimilar] = useState<SimilarResults | null>(null);
  const [viewPreferences, setViewPreferences] = useResultViewPreferences();
  const [showShortcuts, setShowShortcuts] = useState(false);
  const closeShortcuts = useCallback(() => setShowShortcuts(false), []);

  const sidebar = useResizableSidebar();

  const searchMutation = useMutation<SearchResponse, unknown, SearchMutationVariables>({
    mutationFn: ({ payload, signal }) => search(payload, signal),
  });
  const similarMutation = useMutation<
    SimilarSearchResponse,
    unknown,
    { request: SimilarSearchRequest; signal: AbortSignal }
  >({
    mutationFn: ({ request, signal }) => searchSimilar(request, signal),
  });
  const isPending = searchMutation.isPending || similarMutation.isPending;
  const searchError = searchMutation.isError
    ? searchMutation.error
    : similarMutation.isError
      ? similarMutation.error
      : undefined;
  // A running or failed search replaces the results on screen.
  const settled = !isPending && searchError === undefined;
  const response = settled ? shown?.response : undefined;
  const displayed = settled ? (similar?.response ?? response) : undefined;

  useEffect(
    () => () => {
      activeController.current?.abort();
    },
    [],
  );

  // The plan editor (two query boxes per event) needs room; widen only while it is shown, then
  // return to the width the user chose for the regular form.
  const planVisible = activeType === "KIS" && queryUnderstanding && kisPlan !== null;
  const { widenTo, restoreNormal } = sidebar;
  useEffect(() => {
    if (planVisible) widenTo(PLAN_EDITOR_WIDTH);
    else restoreNormal();
  }, [planVisible, widenTo, restoreNormal]);

  // "/" jumps to the query box and "?" lists the shortcuts, unless a field or a dialog has them.
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || isTypingTarget(event.target)) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      if (event.key === "?") {
        event.preventDefault();
        setShowShortcuts(true);
      } else if (event.key === "/") {
        event.preventDefault();
        document.getElementById(QUERY_FIELD_IDS[activeType])?.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [activeType]);

  const resetResults = () => {
    activeController.current?.abort();
    searchMutation.reset();
    similarMutation.reset();
    setSimilar(null);
  };

  const changeTab = (queryType: QueryType) => {
    resetResults();
    setShown(null);
    form.planMutation.reset();
    form.setValidationErrors([]);
    form.setActiveType(queryType);
  };

  /** Always asks the backend; the answer replaces any saved result for the same request. */
  const runSearch = (payload: SearchRequest) => {
    const signal = nextSignal();
    similarMutation.reset();
    setSimilar(null);
    setGroupByVideo(false);
    setGroupSort("score");
    const started = performance.now();
    searchMutation.mutate(
      { payload, signal },
      {
        onSuccess: (result) => {
          const entry = { payload, response: result, at: Date.now() };
          resultCache.put(entry);
          setShown({ ...entry, fromCache: false, elapsedMs: performance.now() - started });
        },
      },
    );
  };

  /** Search keyframes that look like the one picked, keeping the text results to return to. */
  const runSimilar = (videoId: string, frameId: number) => {
    const signal = nextSignal();
    searchMutation.reset();
    const topK = Number(form.state.topK);
    const request: SimilarSearchRequest = {
      video_id: videoId,
      frame_id: frameId,
      top_k:
        Number.isInteger(topK) && topK >= config.min_top_k && topK <= config.max_top_k
          ? topK
          : config.default_top_k,
      model_choices: form.state.modelChoices.length > 0 ? form.state.modelChoices : ["siglip"],
      include_traffic: activeType === "TRAFFIC" || form.state.includeTraffic,
    };
    setProgramFilter("ALL");
    const started = performance.now();
    similarMutation.mutate(
      { request, signal },
      {
        onSuccess: (result) =>
          setSimilar({ request, response: result, elapsedMs: performance.now() - started }),
      },
    );
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload = form.buildPayload();
    if (!payload) return;

    runSearch(payload);
    queryHistory.record(
      payload.query_type === "TRAKE"
        ? {
            type: "TRAKE",
            at: Date.now(),
            mainQuery: payload.main_query ?? "",
            events: payload.events.map((event) => event.query),
            payload,
          }
        : {
            type: payload.query_type === "TRAFFIC" ? "TRAFFIC" : "KIS",
            at: Date.now(),
            query: payload.query,
            payload,
          },
    );
  };

  const restoreQuery = (entry: QueryHistoryEntry) => {
    form.setValidationErrors([]);
    if (!entry.payload) {
      form.restoreQueryText(entry);
      return;
    }
    form.applyForm(formFromRequest(entry.payload));
    const cached = resultCache.get(entry.payload);
    if (cached) {
      // Show the saved answer instead of searching again; "Tìm lại" re-runs it.
      resetResults();
      setGroupByVideo(false);
      setGroupSort("score");
      setProgramFilter("ALL");
      setShown({ ...cached, fromCache: true, elapsedMs: null });
    }
  };

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
          <ThemeSwitcher mode={themeMode} onChange={setThemeMode} />
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
              hasResults={(entry) => Boolean(entry.payload && resultCache.has(entry.payload))}
            />

            {activeType === "KIS" && (
              <KisQueryFields form={form} maxQueryLength={config.max_query_length} />
            )}

            {activeType === "TRAFFIC" && (
              <>
                <label className="field" htmlFor="traffic-query">
                  <span className="field__label">Truy vấn TRAFFIC</span>
                  <AutoGrowTextarea
                    id="traffic-query"
                    className="field__query"
                    value={form.state.trafficQuery}
                    maxLength={config.max_query_length}
                    onChange={(event) => form.setTrafficQuery(event.target.value)}
                    onKeyDown={submitOnEnter}
                    aria-keyshortcuts="Enter Shift+Enter"
                    placeholder="Mô tả xe, người, màu sắc, vị trí. Tên đường, giờ và thời tiết chọn ở bộ lọc bên dưới."
                    rows={3}
                  />
                </label>
                <TrafficFilterPanel
                  filters={form.state.trafficFilters}
                  onChange={form.setTrafficFilters}
                />
              </>
            )}

            {activeType === "TRAKE" && (
              <TrakeQueryFields
                form={form}
                maxQueryLength={config.max_query_length}
                maxEvents={config.max_trake_events}
              />
            )}
          </div>

          <SearchOptionsPanel form={form} />

          {form.validationErrors.length > 0 && (
            <div className="notice notice--error rail__errors" role="alert">
              <strong>Chưa tìm được</strong>
              <ul>
                {form.validationErrors.map((error) => (
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
              value={form.state.topK}
              onChange={(event) => form.setTopK(event.target.value)}
            />
          </label>
          <button
            className="button button--primary rail__search"
            type="submit"
            form="search-form"
            disabled={form.planMutation.isPending || (form.planned && !kisPlan)}
          >
            Tìm kiếm
          </button>
        </footer>
      </aside>

      <div
        className="rail-resizer"
        onMouseDown={(event) => sidebar.startResizing(event, !planVisible)}
        aria-hidden="true"
        title="Kéo để đổi độ rộng"
      />

      <div className="sheet" aria-label="Kết quả tìm kiếm">
        <ResultsToolbar
          response={displayed}
          elapsedMs={similar ? similar.elapsedMs : (shown?.elapsedMs ?? null)}
          saved={
            !similar && shown?.fromCache
              ? { at: shown.at, onSearchAgain: () => runSearch(shown.payload) }
              : null
          }
          similarTo={
            similar && settled
              ? {
                  videoId: similar.request.video_id,
                  frameId: similar.request.frame_id,
                  onBack: shown ? () => setSimilar(null) : null,
                }
              : null
          }
          frameSize={viewPreferences.frameSize}
          onFrameSizeChange={(frameSize) => setViewPreferences({ frameSize })}
          collapseShots={viewPreferences.collapseShots}
          onCollapseShotsChange={(collapseShots) => setViewPreferences({ collapseShots })}
          groupByVideo={groupByVideo}
          onGroupByVideoChange={setGroupByVideo}
          groupSort={groupSort}
          onGroupSortChange={setGroupSort}
          programFilter={programFilter}
          onProgramFilterChange={setProgramFilter}
        />

        {response && !similar && (
          <SearchInsight
            response={response}
            payload={shown?.payload}
            objectTerms={form.state.objectTerms}
            onPinObject={form.pinObject}
          />
        )}
        <div className="sheet__content" data-frame-size={viewPreferences.frameSize}>
          <SearchResultsView
            isPending={isPending}
            error={searchError}
            response={displayed ?? null}
            trakeEventCount={
              !similar && shown?.payload.query_type === "TRAKE" ? shown.payload.events.length : null
            }
            maxAnswerLength={config.max_answer_length}
            groupByVideo={groupByVideo}
            groupSort={groupSort}
            programFilter={programFilter}
            collapseShots={viewPreferences.collapseShots}
            onFindSimilar={runSimilar}
          />
        </div>
        {showShortcuts && <ShortcutsHelp onClose={closeShortcuts} />}
      </div>
    </section>
  );
}
