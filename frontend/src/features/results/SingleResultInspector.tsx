import { useCallback, useEffect, useState } from "react";

import type {
  KISSearchResponse,
  SingleSearchResult,
  TrafficSearchResponse,
  VideoKeyframe,
  VQASearchResponse,
} from "../../api/types";
import { ResultDetailModal, formatMs, formatScore } from "./ResultDetailModal";
import { ResultImage } from "./ResultImage";

interface SingleResultInspectorProps {
  response: KISSearchResponse | VQASearchResponse | TrafficSearchResponse;
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
  const navigateDetail = useCallback((keyframe: VideoKeyframe) => {
    setSelected((current) =>
      current && {
        ...current,
        // Traffic clock time belongs to the original keyframe only.
        result: { ...current.result, ...keyframe, clock_time: null },
      },
    );
  }, []);

  const closeDetail = useCallback(() => {
    const trigger = selected?.trigger;
    setSelected(null);
    window.requestAnimationFrame(() => trigger?.focus());
  }, [selected]);

  return (
    <section className="result-inspector" aria-label="Danh sách kết quả">
      {response.query_type === "VQA" && (
        <label className="field vqa-answer" htmlFor="global-vqa-answer">
          <span className="field__label">Câu trả lời VQA</span>
          <textarea
            id="global-vqa-answer"
            value={globalVQAAnswer}
            maxLength={maxAnswerLength}
            onChange={(e) => setGlobalVQAAnswer(e.target.value)}
            placeholder="Câu trả lời sẽ điền sẵn khi nộp DRES"
            rows={2}
          />
        </label>
      )}

      {groupByVideo ? (
        <div className="video-groups">
          {videoGroups.map(([videoId, results]) => (
            <section className="video-group" data-testid="video-group" key={videoId}>
              <header className="video-group__head">
                <h2>{videoId}</h2>
                <span>{results.length} kết quả</span>
              </header>
              <ol className="contact-sheet" aria-label={`Kết quả của ${videoId}`}>
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
        <ol className="contact-sheet" aria-label="Kết quả theo thứ hạng">
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
          onNavigate={navigateDetail}
          submitTarget={{
            kind: "single",
            videoId: selected.result.video_id,
            frameId: selected.result.frame_id,
            timeMs: selected.result.time_ms ?? null,
            defaultMode: response.query_type === "VQA" ? "VQA" : "KIS",
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

function ResultCard({ result, rank, onOpenDetail }: ResultCardProps) {
  const time =
    result.time_ms !== null && result.time_ms !== undefined
      ? formatMs(result.time_ms)
      : `F${result.frame_id}`;
  return (
    <li className="frame" data-testid="result-card">
      <article aria-label={`Hạng ${rank}, ${result.video_id}`}>
        <button
          type="button"
          className="frame__image"
          onClick={(event) => onOpenDetail(event.currentTarget)}
          aria-label={`Mở chi tiết ${result.video_id}, frame ${result.frame_id}`}
        >
          <ResultImage
            src={result.keyframe_url}
            alt={`Keyframe ${result.frame_id} của ${result.video_id}`}
          />
        </button>
        <footer className="frame__edge">
          <span className="frame__rank">{rank}</span>
          <strong className="frame__video">{result.video_id}</strong>
          <span className="frame__time">{time}</span>
          <span className="frame__score" title="Điểm tương đồng">
            {formatScore(result.similarity_score)}
          </span>
        </footer>
        {result.camera_name && (
          <p className="frame__meta" title={result.camera_name}>
            <span>{result.camera_name}</span>
            {result.clock_time && <span>{result.clock_time.slice(6)}</span>}
          </p>
        )}
      </article>
    </li>
  );
}
