import {
  type CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import type {
  TRAKEEventResult,
  TRAKESearchResponse,
  TRAKESearchResult,
  VideoKeyframe,
} from "../../api/types";
import {
  type ResultDetail,
  ResultDetailModal,
  formatScore,
} from "./ResultDetailModal";
import { ResultImage } from "./ResultImage";
import { validateTrakeResults } from "./trakeValidation";

interface TrakeResultInspectorProps {
  response: TRAKESearchResponse;
  expectedEventCount: number;
}

interface SelectedEvent {
  result: ResultDetail;
  row: TRAKESearchResult;
  eventIndex: number;
  trigger: HTMLButtonElement;
}

export function TrakeResultInspector({
  response,
  expectedEventCount,
}: TrakeResultInspectorProps) {
  const validationErrors = useMemo(
    () => validateTrakeResults(response.results, expectedEventCount),
    [expectedEventCount, response.results],
  );
  const [selected, setSelected] = useState<SelectedEvent | null>(null);

  useEffect(() => {
    setSelected(null);
  }, [response.results]);

  const orderedResults = response.results;

  const openEventDetail = (
    row: TRAKESearchResult,
    event: TRAKEEventResult,
    trigger: HTMLButtonElement,
  ) => {
    setSelected({
      result: { ...event, video_id: row.video_id },
      row,
      eventIndex: event.event_index,
      trigger,
    });
  };

  // Picking a neighbouring keyframe replaces this EVENT's frame in the submission.
  const navigateDetail = useCallback((keyframe: VideoKeyframe) => {
    setSelected((current) => {
      if (!current) return current;
      const events = current.row.events.map((event) =>
        event.event_index === current.eventIndex ? { ...event, ...keyframe } : event,
      );
      return {
        ...current,
        result: { ...current.result, ...keyframe },
        row: { ...current.row, events },
      };
    });
  }, []);

  const closeDetail = useCallback(() => {
    const trigger = selected?.trigger;
    setSelected(null);
    window.requestAnimationFrame(() => trigger?.focus());
  }, [selected]);

  if (validationErrors.length > 0) {
    return (
      <section className="trake-validation-error" role="alert">
        <strong>Cannot display malformed TRAKE results</strong>
        <p>The response does not match the submitted EVENT sequence.</p>
        <ul>
          {validationErrors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      </section>
    );
  }

  return (
    <section className="result-inspector" aria-label="TRAKE search results">
      <div
        className="trake-table-scroll"
        data-testid="trake-scroll-container"
        style={{ overflowX: "auto" }}
      >
        <ol className="trake-row-list" aria-label="TRAKE candidate rows">
          {orderedResults.map((result, index) => (
            <TrakeRow
              key={result.result_id}
              result={result}
              rank={index + 1}
              eventCount={expectedEventCount}
              onOpenDetail={(event, trigger) => openEventDetail(result, event, trigger)}
            />
          ))}
        </ol>
      </div>

      {selected && (
        <ResultDetailModal
          result={selected.result}
          onClose={closeDetail}
          onNavigate={navigateDetail}
          submitTarget={{
            kind: "trake",
            videoId: selected.row.video_id,
            frameIds: selected.row.events.map((event) => event.frame_id),
            eventIndex: selected.eventIndex,
          }}
        />
      )}
    </section>
  );
}

interface TrakeRowProps {
  result: TRAKESearchResult;
  rank: number;
  eventCount: number;
  onOpenDetail: (event: TRAKEEventResult, trigger: HTMLButtonElement) => void;
}

function TrakeRow({
  result,
  rank,
  eventCount,
  onOpenDetail,
}: TrakeRowProps) {
  const style = {
    "--event-count": eventCount,
  } as CSSProperties;

  return (
    <li className="trake-row" style={style} data-testid="trake-row">
      <article className="trake-row__identity" aria-label={`Rank ${rank}, ${result.video_id}`}>
        <div className="trake-row__video">
          <strong>{result.video_id}</strong>
          <span>Score {formatScore(result.similarity_score)}</span>
        </div>
      </article>

      {result.events.map((event) => (
        <article
          className="trake-event-cell"
          data-testid="trake-event-cell"
          key={event.event_index}
          aria-label={`EVENT ${event.event_index}`}
        >
          <div className="trake-event-cell__heading">
            <strong>EVENT {event.event_index}</strong>
            <span>{formatScore(event.similarity_score)}</span>
          </div>
          <button
            type="button"
            className="thumbnail-button trake-event-cell__thumbnail"
            onClick={(clickEvent) => onOpenDetail(event, clickEvent.currentTarget)}
            aria-label={`Open EVENT ${event.event_index} details for ${result.video_id}, frame ${event.frame_id}`}
          >
            <ResultImage
              src={event.keyframe_url}
              alt={`EVENT ${event.event_index}, frame ${event.frame_id} from ${result.video_id}`}
              className="result-card__image"
            />
          </button>
          <dl className="trake-event-cell__metadata">
            <div>
              <dt>Frame</dt>
              <dd>{event.frame_id}</dd>
            </div>
            <div>
              <dt>Segment</dt>
              <dd>{event.segment_id || "—"}</dd>
            </div>
          </dl>
        </article>
      ))}
    </li>
  );
}
