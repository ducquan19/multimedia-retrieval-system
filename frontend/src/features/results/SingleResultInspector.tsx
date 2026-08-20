import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
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
  rectSortingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import type {
  KISSearchResponse,
  SingleSearchResult,
  VQASearchResponse,
} from "../../api/types";
import { ResultDetailModal, formatScore } from "./ResultDetailModal";
import { ResultImage } from "./ResultImage";
import { createResultEditorState, resultEditorReducer } from "./resultState";

interface SingleResultInspectorProps {
  response: KISSearchResponse | VQASearchResponse;
  maxAnswerLength: number;
}

interface SelectedResult {
  result: SingleSearchResult;
  trigger: HTMLButtonElement;
}

export function SingleResultInspector({
  response,
  maxAnswerLength,
}: SingleResultInspectorProps) {
  const [state, dispatch] = useReducer(
    resultEditorReducer,
    response.results,
    createResultEditorState,
  );
  const [selected, setSelected] = useState<SelectedResult | null>(null);
  const [globalVQAAnswer, setGlobalVQAAnswer] = useState("");

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  useEffect(() => {
    dispatch({ type: "initialize", results: response.results });
    setSelected(null);
    setGlobalVQAAnswer("");
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
  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    dispatch({ type: "move", activeId: String(active.id), overId: String(over.id) });
  };

  const closeDetail = useCallback(() => {
    const trigger = selected?.trigger;
    setSelected(null);
    window.requestAnimationFrame(() => trigger?.focus());
  }, [selected]);

  return (
    <section className="result-inspector" aria-labelledby="result-inspector-heading">
      <div className="result-inspector__heading">
        <div>
          <p className="eyebrow eyebrow--dark">Editable result order</p>
          <h3 id="result-inspector-heading">{orderedResults.length} candidates</h3>
        </div>
        <div className="result-inspector__actions">
          <span className="mini-badge">{response.query_type}</span>
          <button
            type="button"
            className="secondary-button"
            disabled={!orderChanged}
            onClick={() => dispatch({ type: "reset-order" })}
          >
            Reset order
          </button>
        </div>
      </div>

      {response.query_type === "VQA" && (
        <div style={{ marginBottom: "1rem" }}>
          <label className="field" htmlFor="global-vqa-answer">
            <span>VQA Answer</span>
            <textarea
              id="global-vqa-answer"
              value={globalVQAAnswer}
              maxLength={maxAnswerLength}
              onChange={(e) => setGlobalVQAAnswer(e.target.value)}
              placeholder="Nhập câu trả lời VQA vào đây..."
              rows={3}
            />
          </label>
        </div>
      )}

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={state.order} strategy={rectSortingStrategy}>
          <ol className="result-card-grid" aria-label="Retrieved candidates">
            {orderedResults.map((result, index) => (
              <SortableResultCard
                key={result.result_id}
                result={result}
                rank={index + 1}
                canMoveUp={index > 0}
                canMoveDown={index < orderedResults.length - 1}
                onMove={(offset) =>
                  dispatch({ type: "move-by", resultId: result.result_id, offset })
                }
                onOpenDetail={(trigger) => setSelected({ result, trigger })}
              />
            ))}
          </ol>
        </SortableContext>
      </DndContext>

      {selected && <ResultDetailModal result={selected.result} onClose={closeDetail} />}
    </section>
  );
}

interface SortableResultCardProps {
  result: SingleSearchResult;
  rank: number;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMove: (offset: -1 | 1) => void;
  onOpenDetail: (trigger: HTMLButtonElement) => void;
}

function SortableResultCard({
  result,
  rank,
  canMoveUp,
  canMoveDown,
  onMove,
  onOpenDetail,
}: SortableResultCardProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: result.result_id,
  });

  return (
    <li
      ref={setNodeRef}
      className={`result-card${isDragging ? " result-card--dragging" : ""}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      data-testid="result-card"
    >
      <article aria-label={`Rank ${rank}, ${result.video_id}`}>
        <div className="result-card__media">
          <button
            type="button"
            className="thumbnail-button"
            onClick={(event) => onOpenDetail(event.currentTarget)}
            aria-label={`Open details for ${result.video_id}, frame ${result.frame_id}`}
            {...attributes}
            {...listeners}
            style={{ cursor: 'grab' }}
          >
            <ResultImage
              src={result.keyframe_url}
              alt={`Keyframe ${result.frame_id} from ${result.video_id}`}
              className="result-card__image"
            />
          </button>
        </div>

        <div className="result-card__body">
          <div className="result-card__title-row">
            <div>
              <strong>{result.video_id}</strong>
              <span>Frame {result.frame_id}</span>
            </div>
            <span className="score-badge">{formatScore(result.similarity_score)}</span>
          </div>
          <div className="result-card__controls" aria-label={`Reorder ${result.video_id}`}>
            <button
              type="button"
              className="secondary-button"
              disabled={!canMoveUp}
              onClick={() => onMove(-1)}
              onPointerDown={(event) => event.stopPropagation()}
            >
              Move up
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={!canMoveDown}
              onClick={() => onMove(1)}
              onPointerDown={(event) => event.stopPropagation()}
            >
              Move down
            </button>
          </div>
        </div>
      </article>
    </li>
  );
}
