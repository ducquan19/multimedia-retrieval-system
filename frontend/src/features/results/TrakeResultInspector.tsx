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
      <section className="sheet-state sheet-state--error" role="alert">
        <strong>Kết quả TRAKE không hợp lệ</strong>
        <p>Phản hồi không khớp với chuỗi EVENT đã gửi.</p>
        <ul>
          {validationErrors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      </section>
    );
  }

  return (
    <section className="result-inspector" aria-label="Kết quả TRAKE">
      <div className="strips" data-testid="trake-scroll-container" style={{ overflowX: "auto" }}>
        <ol className="strips__list" aria-label="Chuỗi ứng viên TRAKE">
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

function TrakeRow({ result, rank, eventCount, onOpenDetail }: TrakeRowProps) {
  const style = { "--event-count": eventCount } as CSSProperties;

  return (
    <li className="strip" style={style} data-testid="trake-row">
      <header className="strip__label" aria-label={`Hạng ${rank}, ${result.video_id}`}>
        <span className="strip__rank">{rank}</span>
        <strong className="strip__video">{result.video_id}</strong>
        <span className="strip__score" title="Tổng điểm chuỗi">
          {formatScore(result.similarity_score)}
        </span>
      </header>

      {result.events.map((event) => (
        <article
          className="strip__event"
          data-testid="trake-event-cell"
          key={event.event_index}
          aria-label={`EVENT ${event.event_index}`}
        >
          <button
            type="button"
            className="frame__image"
            onClick={(clickEvent) => onOpenDetail(event, clickEvent.currentTarget)}
            aria-label={`Mở EVENT ${event.event_index} của ${result.video_id}, frame ${event.frame_id}`}
          >
            <ResultImage
              src={event.keyframe_url}
              alt={`EVENT ${event.event_index}, frame ${event.frame_id} của ${result.video_id}`}
            />
          </button>
          <footer
            className="frame__edge"
            title={event.segment_id ? `Shot ${event.segment_id}` : undefined}
          >
            <span className="frame__rank">E{event.event_index}</span>
            <span className="frame__time">F{event.frame_id}</span>
            <span className="frame__score">{formatScore(event.similarity_score)}</span>
          </footer>
        </article>
      ))}
    </li>
  );
}
