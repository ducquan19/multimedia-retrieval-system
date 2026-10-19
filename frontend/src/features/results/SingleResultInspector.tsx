import { useCallback, useEffect, useState } from "react";

import type { SingleFrameResponse, SingleSearchResult, VideoKeyframe } from "../../api/types";
import { AutoGrowTextarea } from "../../shared/AutoGrowTextarea";
import { ResultDetailModal, formatMs, formatScore } from "./ResultDetailModal";
import { ResultImage } from "./ResultImage";
import { moveFocusInGrid, type ShownResult, shownResults } from "./resultBrowsing";

interface SingleResultInspectorProps {
  response: SingleFrameResponse;
  maxAnswerLength: number;
  groupByVideo?: boolean;
  groupSort?: "score" | "time";
  /** Keep only the best result of each shot. */
  collapseShots?: boolean;
  /** When set, results offer a search for keyframes that look like them. */
  onFindSimilar?: (videoId: string, frameId: number) => void;
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
  collapseShots = false,
  onFindSimilar,
}: SingleResultInspectorProps) {
  const [selected, setSelected] = useState<SelectedResult | null>(null);
  const [globalVQAAnswer, setGlobalVQAAnswer] = useState("");
  // Results opened in the detail view, and videos ruled out, for this response only.
  const [seen, setSeen] = useState<ReadonlySet<string>>(() => new Set());
  const [hiddenVideos, setHiddenVideos] = useState<ReadonlySet<string>>(() => new Set());

  useEffect(() => {
    setSelected(null);
    setGlobalVQAAnswer("");
    setSeen(new Set());
    setHiddenVideos(new Set());
  }, [response.results]);

  const shown = shownResults(response.results, { collapse: collapseShots, hiddenVideos });
  const videoGroups = Array.from(
    shown
      .reduce((groups, item) => {
        const group = groups.get(item.result.video_id) ?? [];
        group.push(item);
        groups.set(item.result.video_id, group);
        return groups;
      }, new Map<string, ShownResult[]>())
      .entries(),
  ).map(
    ([videoId, items]) =>
      [
        videoId,
        [...items].sort((left, right) =>
          groupSort === "score"
            ? right.result.similarity_score - left.result.similarity_score
            : left.result.frame_id - right.result.frame_id,
        ),
      ] as const,
  );

  const openDetail = (result: SingleSearchResult, trigger: HTMLButtonElement) => {
    setSelected({ result, trigger });
    setSeen((current) => new Set(current).add(result.result_id));
  };

  const navigateDetail = useCallback((keyframe: VideoKeyframe) => {
    setSelected(
      (current) =>
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

  const hideVideo = (videoId: string) => {
    setHiddenVideos((current) => new Set(current).add(videoId));
    setSelected(null);
  };

  const findSimilar =
    onFindSimilar &&
    ((videoId: string, frameId: number) => {
      setSelected(null);
      onFindSimilar(videoId, frameId);
    });

  const renderSheet = (items: ShownResult[], label: string) => (
    <ol
      className="contact-sheet"
      aria-label={label}
      onKeyDown={(event) => moveFocusInGrid(event, ".frame__image")}
    >
      {items.map((item) => (
        <ResultCard
          key={item.result.result_id}
          item={item}
          seen={seen.has(item.result.result_id)}
          onOpenDetail={(trigger) => openDetail(item.result, trigger)}
        />
      ))}
    </ol>
  );

  return (
    <section className="result-inspector" aria-label="Danh sách kết quả">
      {response.query_type === "VQA" && (
        <label className="field vqa-answer" htmlFor="global-vqa-answer">
          <span className="field__label">Câu trả lời VQA</span>
          <AutoGrowTextarea
            id="global-vqa-answer"
            value={globalVQAAnswer}
            maxLength={maxAnswerLength}
            onChange={(e) => setGlobalVQAAnswer(e.target.value)}
            placeholder="Câu trả lời sẽ điền sẵn khi nộp DRES"
            rows={2}
          />
        </label>
      )}

      {hiddenVideos.size > 0 && (
        <p className="notice result-inspector__hidden" role="status">
          Đã ẩn {hiddenVideos.size} video: {Array.from(hiddenVideos).join(", ")}
          <button
            type="button"
            className="button button--text"
            onClick={() => setHiddenVideos(new Set())}
          >
            Hiện lại
          </button>
        </p>
      )}

      {groupByVideo ? (
        <div className="video-groups">
          {videoGroups.map(([videoId, items]) => (
            <section className="video-group" data-testid="video-group" key={videoId}>
              <header className="video-group__head">
                <h2>{videoId}</h2>
                <span>{items.length} kết quả</span>
              </header>
              {renderSheet(items, `Kết quả của ${videoId}`)}
            </section>
          ))}
        </div>
      ) : (
        renderSheet(shown, "Kết quả theo thứ hạng")
      )}

      {selected && (
        <ResultDetailModal
          result={selected.result}
          onClose={closeDetail}
          onNavigate={navigateDetail}
          onFindSimilar={findSimilar}
          onHideVideo={hideVideo}
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
  item: ShownResult;
  seen: boolean;
  onOpenDetail: (trigger: HTMLButtonElement) => void;
}

function ResultCard({ item, seen, onOpenDetail }: ResultCardProps) {
  const { result, rank, folded } = item;
  const time =
    result.time_ms !== null && result.time_ms !== undefined
      ? formatMs(result.time_ms)
      : `F${result.frame_id}`;
  const status = [seen ? "đã xem" : null, folded ? `gộp thêm ${folded} ảnh cùng shot` : null]
    .filter(Boolean)
    .join(", ");
  return (
    <li className="frame" data-testid="result-card" data-seen={seen || undefined}>
      <article aria-label={`Hạng ${rank}, ${result.video_id}`}>
        <button
          type="button"
          className="frame__image"
          onClick={(event) => onOpenDetail(event.currentTarget)}
          aria-label={`Mở chi tiết ${result.video_id}, frame ${result.frame_id}${status ? `, ${status}` : ""}`}
        >
          <ResultImage
            src={result.keyframe_url}
            alt={`Keyframe ${result.frame_id} của ${result.video_id}`}
          />
          {folded > 0 && (
            <span className="frame__folded" aria-hidden="true">
              +{folded}
            </span>
          )}
          {seen && (
            <span className="frame__seen" aria-hidden="true">
              Đã xem
            </span>
          )}
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
