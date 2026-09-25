import { type CSSProperties, useCallback, useEffect, useState } from "react";

import type {
  KISSearchResponse,
  SingleSearchResult,
  VQASearchResponse,
} from "../../api/types";
import { ResultDetailModal, formatScore } from "./ResultDetailModal";
import { ResultImage } from "./ResultImage";

interface SingleResultInspectorProps {
  response: KISSearchResponse | VQASearchResponse;
  maxAnswerLength: number;
  groupByVideo?: boolean;
  groupSort?: "score" | "time";
}

interface SelectedResult {
  result: SingleSearchResult;
  trigger: HTMLButtonElement;
}

export function SingleResultInspector({
  response,
  maxAnswerLength,
  groupByVideo = false,
  groupSort = "score",
}: SingleResultInspectorProps) {
  const [selected, setSelected] = useState<SelectedResult | null>(null);
  const [globalVQAAnswer, setGlobalVQAAnswer] = useState("");

  useEffect(() => {
    setSelected(null);
    setGlobalVQAAnswer("");
  }, [response.results]);

  const orderedResults = response.results;
  const resultRankById = new Map(
    orderedResults.map((result, index) => [result.result_id, index + 1]),
  );
  const videoGroups = Array.from(
    orderedResults
      .reduce((groups, result) => {
        const group = groups.get(result.video_id) ?? [];
        group.push(result);
        groups.set(result.video_id, group);
        return groups;
      }, new Map<string, SingleSearchResult[]>())
      .entries(),
  ).map(([videoId, results]) => [
    videoId,
    [...results].sort((left, right) =>
      groupSort === "score"
        ? right.similarity_score - left.similarity_score
        : left.frame_id - right.frame_id,
    ),
  ] as const);
  const closeDetail = useCallback(() => {
    const trigger = selected?.trigger;
    setSelected(null);
    window.requestAnimationFrame(() => trigger?.focus());
  }, [selected]);

  return (
    <section className="result-inspector" aria-label="Search results">
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

      {groupByVideo ? (
        <div className="result-video-groups">
          {videoGroups.map(([videoId, results]) => (
            <section
              className="result-video-group"
              data-testid="video-group"
              key={videoId}
              style={{ "--group-columns": Math.min(results.length, 5) } as CSSProperties}
            >
              <header className="result-video-group__heading">
                <h4>{videoId}</h4>
                <span>{results.length} result{results.length === 1 ? "" : "s"}</span>
              </header>
              <ol className="result-card-grid" aria-label={`Results from ${videoId}`}>
                {results.map((result) => (
                  <ResultCard
                    key={result.result_id}
                    result={result}
                    rank={resultRankById.get(result.result_id) ?? 0}
                    onOpenDetail={(trigger) => setSelected({ result, trigger })}
                  />
                ))}
              </ol>
            </section>
          ))}
        </div>
      ) : (
        <ol className="result-card-grid" aria-label="Retrieved candidates">
          {orderedResults.map((result, index) => (
            <ResultCard
              key={result.result_id}
              result={result}
              rank={index + 1}
              onOpenDetail={(trigger) => setSelected({ result, trigger })}
            />
          ))}
        </ol>
      )}

      {selected && (
        <ResultDetailModal
          result={selected.result}
          onClose={closeDetail}
          submitTarget={{
            kind: "single",
            videoId: selected.result.video_id,
            frameId: selected.result.frame_id,
            defaultMode: response.query_type,
            answer: globalVQAAnswer,
          }}
        />
      )}
    </section>
  );
}

interface ResultCardProps {
  result: SingleSearchResult;
  rank: number;
  onOpenDetail: (trigger: HTMLButtonElement) => void;
}

function ResultCard({
  result,
  rank,
  onOpenDetail,
}: ResultCardProps) {
  return (
    <li className="result-card" data-testid="result-card">
      <article aria-label={`Rank ${rank}, ${result.video_id}`}>
        <div className="result-card__media">
          <button
            type="button"
            className="thumbnail-button"
            onClick={(event) => onOpenDetail(event.currentTarget)}
            aria-label={`Open details for ${result.video_id}, frame ${result.frame_id}`}
          >
            <ResultImage
              src={result.keyframe_url}
              alt={`Keyframe ${result.frame_id} from ${result.video_id}`}
              className="result-card__image"
            />
          </button>
          <span className="score-badge result-card__score">
            {formatScore(result.similarity_score)}
          </span>
        </div>

        <div className="result-card__body">
          <div className="result-card__title-row">
            <strong>{result.video_id}</strong>
            <span>{result.frame_id}</span>
          </div>
        </div>
      </article>
    </li>
  );
}
