import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { getVideoKeyframes } from "../../api/client";
import type { VideoKeyframe } from "../../api/types";
import { formatMs } from "./ResultDetailModal";
import { ResultImage } from "./ResultImage";

export const TEMPORAL_RADIUS = 8;

/** Keyframes around `frameId` in the same video; `centerIndex` points at the current one. */
export function useVideoKeyframes(videoId: string, frameId: number, enabled = true) {
  const query = useQuery({
    queryKey: ["video-keyframes", videoId, frameId, TEMPORAL_RADIUS],
    queryFn: ({ signal }) => getVideoKeyframes(videoId, frameId, TEMPORAL_RADIUS, signal),
    enabled,
    retry: false,
    staleTime: Infinity,
    // Keep the previous strip on screen while the re-centered window loads.
    placeholderData: (previous) => (previous?.video_id === videoId ? previous : undefined),
  });
  const keyframes = query.data?.keyframes ?? [];
  const centerIndex = keyframes.findIndex((keyframe) => keyframe.frame_id === frameId);
  return {
    query,
    keyframes,
    centerIndex: centerIndex >= 0 ? centerIndex : (query.data?.center_index ?? -1),
  };
}

interface TemporalStripProps {
  keyframes: VideoKeyframe[];
  currentFrameId: number;
  isLoading: boolean;
  isError: boolean;
  onSelect: (keyframe: VideoKeyframe) => void;
}

export function TemporalStrip({
  keyframes,
  currentFrameId,
  isLoading,
  isError,
  onSelect,
}: TemporalStripProps) {
  const currentRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    currentRef.current?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [currentFrameId, keyframes]);

  return (
    <section className="temporal-strip" aria-label="Temporal context">
      <header className="temporal-strip__header">
        <h3>Keyframe lân cận</h3>
        <span>
          <kbd>←</kbd> <kbd>→</kbd> chuyển keyframe; khi đang phát video, giữ thêm <kbd>Shift</kbd>
        </span>
      </header>
      {isError ? (
        <p className="temporal-strip__status">Không tải được keyframe lân cận.</p>
      ) : isLoading && keyframes.length === 0 ? (
        <p className="temporal-strip__status">Đang tải…</p>
      ) : (
        <ol className="temporal-strip__list">
          {keyframes.map((keyframe) => {
            const isCurrent = keyframe.frame_id === currentFrameId;
            return (
              <li key={keyframe.frame_id}>
                <button
                  ref={isCurrent ? currentRef : undefined}
                  type="button"
                  className="temporal-strip__item"
                  aria-current={isCurrent ? "true" : undefined}
                  aria-label={`Keyframe ${keyframe.frame_id}`}
                  onClick={() => onSelect(keyframe)}
                >
                  <ResultImage src={keyframe.keyframe_url} alt="" />
                  <span>
                    {keyframe.time_ms !== null && keyframe.time_ms !== undefined
                      ? formatMs(keyframe.time_ms)
                      : `F${keyframe.frame_id}`}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
