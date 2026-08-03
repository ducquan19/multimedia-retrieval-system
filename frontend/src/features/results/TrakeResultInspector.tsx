import {
  type CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useState,
} from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  type DragEndEvent,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import type {
  TRAKEEventResult,
  TRAKESearchResponse,
  TRAKESearchResult,
  SubmissionRequest,
} from "../../api/types";
import { SubmissionActions } from "../submissions/SubmissionActions";
import {
  type ResultDetail,
  ResultDetailModal,
  formatScore,
} from "./ResultDetailModal";
import { ResultImage } from "./ResultImage";
import { createResultEditorState, resultEditorReducer } from "./resultState";
import { validateTrakeResults } from "./trakeValidation";

interface TrakeResultInspectorProps {
  response: TRAKESearchResponse;
  expectedEventCount: number;
}

interface SelectedEvent {
  result: ResultDetail;
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
  const [state, dispatch] = useReducer(
    resultEditorReducer,
    response.results,
    createResultEditorState,
  );
  const [selected, setSelected] = useState<SelectedEvent | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  useEffect(() => {
    dispatch({ type: "initialize", results: response.results });
    setSelected(null);
  }, [response.results]);

  const resultsById = useMemo(
    () => new Map(response.results.map((result) => [result.result_id, result])),
    [response.results],
  );
  const orderedResults = state.order.flatMap((resultId) => {
    const result = resultsById.get(resultId);
    return result ? [result] : [];
  });
  const orderChanged = state.order.some(
    (resultId, index) => resultId !== state.initialOrder[index],
  );

  const buildSubmissionPayload = (filename: string): SubmissionRequest => ({
    query_type: "TRAKE",
    filename,
    event_count: expectedEventCount,
    rows: orderedResults.map((result) => ({
      video_id: result.video_id,
      frame_ids: result.events.map((event) => event.frame_id),
    })),
  });

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    dispatch({ type: "move", activeId: String(active.id), overId: String(over.id) });
  };

  const openEventDetail = (
    row: TRAKESearchResult,
    event: TRAKEEventResult,
    trigger: HTMLButtonElement,
  ) => {
    setSelected({ result: { ...event, video_id: row.video_id }, trigger });
  };

  const closeDetail = useCallback(() => {
    const trigger = selected?.trigger;
    setSelected(null);
    window.requestAnimationFrame(() => trigger?.focus());
  }, [selected]);

  if (validationErrors.length > 0) {
    return (
      <section className="trake-validation-error" role="alert">
        <strong>Cannot display malformed TRAKE results</strong>
        <p>The response does not match the submitted event sequence.</p>
        <ul>
          {validationErrors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      </section>
    );
  }

  return (
    <section className="result-inspector" aria-labelledby="trake-inspector-heading">
      <div className="result-inspector__heading">
        <div>
          <p className="eyebrow eyebrow--dark">Temporal candidate rows</p>
          <h3 id="trake-inspector-heading">{orderedResults.length} candidates</h3>
          <p>
            Reorder complete video rows. Events stay fixed from Event 1 to Event {expectedEventCount}.
          </p>
        </div>
        <div className="result-inspector__actions">
          <span className="mini-badge">TRAKE</span>
        </div>
      </div>

      <div
        className="trake-table-scroll"
        data-testid="trake-scroll-container"
        style={{ overflowX: "auto" }}
      >
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={state.order} strategy={verticalListSortingStrategy}>
            <ol className="trake-row-list" aria-label="TRAKE candidate rows">
              {orderedResults.map((result, index) => (
                <SortableTrakeRow
                  key={result.result_id}
                  result={result}
                  rank={index + 1}
                  eventCount={expectedEventCount}
                  canMoveUp={index > 0}
                  canMoveDown={index < orderedResults.length - 1}
                  onMove={(offset) =>
                    dispatch({ type: "move-by", resultId: result.result_id, offset })
                  }
                  onOpenDetail={(event, trigger) => openEventDetail(result, event, trigger)}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>
      </div>

      <SubmissionActions
        queryType="TRAKE"
        rowCount={orderedResults.length}
        orderChanged={orderChanged}
        stateVersion={JSON.stringify(state.order)}
        onResetOrder={() => dispatch({ type: "reset-order" })}
        buildPayload={buildSubmissionPayload}
      />

      {selected && <ResultDetailModal result={selected.result} onClose={closeDetail} />}
    </section>
  );
}

interface SortableTrakeRowProps {
  result: TRAKESearchResult;
  rank: number;
  eventCount: number;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMove: (offset: -1 | 1) => void;
  onOpenDetail: (event: TRAKEEventResult, trigger: HTMLButtonElement) => void;
}

function SortableTrakeRow({
  result,
  rank,
  eventCount,
  canMoveUp,
  canMoveDown,
  onMove,
  onOpenDetail,
}: SortableTrakeRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: result.result_id,
  });
  const style = {
    "--event-count": eventCount,
    minWidth: `${15 + eventCount * 13}rem`,
    transform: CSS.Transform.toString(transform),
    transition,
  } as CSSProperties;

  return (
    <li
      ref={setNodeRef}
      className={`trake-row${isDragging ? " trake-row--dragging" : ""}`}
      style={style}
      data-testid="trake-row"
    >
      <article className="trake-row__identity" aria-label={`Rank ${rank}, ${result.video_id}`}>
        <div className="trake-row__rank" aria-label={`Current rank ${rank}`}>
          #{rank}
        </div>
        <div className="trake-row__video">
          <strong>{result.video_id}</strong>
          <small>{result.result_id}</small>
          <span>Row score {formatScore(result.similarity_score)}</span>
        </div>
        <div className="trake-row__controls">
          <button
            type="button"
            className="drag-handle"
            aria-label={`Drag result ${result.result_id}`}
            {...attributes}
            {...listeners}
          >
            <span aria-hidden="true">⠿</span>
            Drag row
          </button>
          <div className="move-actions" aria-label={`Move result ${result.result_id}`}>
            <button
              type="button"
              disabled={!canMoveUp}
              onClick={() => onMove(-1)}
              aria-label={`Move result ${result.result_id} up`}
            >
              ↑
            </button>
            <button
              type="button"
              disabled={!canMoveDown}
              onClick={() => onMove(1)}
              aria-label={`Move result ${result.result_id} down`}
            >
              ↓
            </button>
          </div>
        </div>
      </article>

      {result.events.map((event) => (
        <article
          className="trake-event-cell"
          data-testid="trake-event-cell"
          key={event.event_index}
          aria-label={`Event ${event.event_index}`}
        >
          <div className="trake-event-cell__heading">
            <strong>Event {event.event_index}</strong>
            <span>{formatScore(event.similarity_score)}</span>
          </div>
          <button
            type="button"
            className="thumbnail-button trake-event-cell__thumbnail"
            onClick={(clickEvent) => onOpenDetail(event, clickEvent.currentTarget)}
            aria-label={`Open Event ${event.event_index} details for ${result.video_id}, frame ${event.frame_id}`}
          >
            <ResultImage
              src={event.keyframe_url}
              alt={`Event ${event.event_index}, frame ${event.frame_id} from ${result.video_id}`}
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
