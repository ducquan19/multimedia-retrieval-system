import { type MouseEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { getVideoSource, resolveMediaUrl } from "../../api/client";
import type { VideoKeyframe, VideoSourceResponse } from "../../api/types";
import { DresSubmitPanel, type SubmitTarget } from "../submission/DresSubmitPanel";
import { ResultImage } from "./ResultImage";
import { TemporalStrip, useVideoKeyframes } from "./TemporalStrip";
import { useModalAccessibility } from "./useModalAccessibility";

export interface ResultDetail {
  video_id: string;
  frame_id: number;
  keyframe_url: string;
  segment_id: string;
  asr_text: string;
  objects: Record<string, unknown>[];
  similarity_score: number;
  time_ms?: number | null;
  camera_name?: string | null;
  clock_time?: string | null;
  weather?: string | null;
}

interface ResultDetailModalProps {
  result: ResultDetail;
  onClose: () => void;
  /** When set, the modal offers a DRES submission for this result. */
  submitTarget?: SubmitTarget;
  /** When set, the modal shows neighbouring keyframes and moves to the one picked. */
  onNavigate?: (keyframe: VideoKeyframe) => void;
}

function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

export function formatScore(score: number): string {
  return score.toFixed(4);
}

/** 83456 -> "01:23.456" */
export function formatMs(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.floor((ms % 60_000) / 1000);
  const millis = ms % 1000;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(
    millis,
  ).padStart(3, "0")}`;
}

export function ResultDetailModal({
  result,
  onClose,
  submitTarget,
  onNavigate,
}: ResultDetailModalProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameInputRef = useRef<HTMLInputElement>(null);
  useModalAccessibility({ dialogRef, initialFocusRef: closeButtonRef, onClose });
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
  const [videoSource, setVideoSource] = useState<VideoSourceResponse | null>(null);
  const [videoStatus, setVideoStatus] = useState<"idle" | "loading" | "error">("idle");
  const [frameInput, setFrameInput] = useState(String(result.frame_id));
  const [frameCopyStatus, setFrameCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
  const [showSubmit, setShowSubmit] = useState(false);
  // VFR videos (traffic) are navigated by original time in ms instead of frame index.
  const keyframeTimeMs = result.time_ms ?? null;
  const timeMode = keyframeTimeMs !== null;
  const [timeInput, setTimeInput] = useState(String(keyframeTimeMs ?? ""));
  const parsedFrameInput = Number(frameInput);
  const currentFrame =
    !timeMode && videoSource && frameInput.trim() !== "" && Number.isInteger(parsedFrameInput)
      ? parsedFrameInput
      : null;
  const parsedTimeInput = Number(timeInput);
  const currentTimeMs =
    timeMode && videoSource && timeInput.trim() !== "" && Number.isInteger(parsedTimeInput)
      ? parsedTimeInput
      : null;

  const neighbours = useVideoKeyframes(result.video_id, result.frame_id, Boolean(onNavigate));

  const closeOnBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  const toggleVideo = async () => {
    if (videoSource) {
      setVideoSource(null);
      setVideoStatus("idle");
      return;
    }

    setVideoStatus("loading");
    try {
      setVideoSource(await getVideoSource(result.video_id));
      setVideoStatus("idle");
    } catch {
      setVideoStatus("error");
    }
  };

  const setVideoTimeMs = (requestedMs: number): HTMLVideoElement | null => {
    const video = videoRef.current;
    if (!video || !videoSource) return null;
    const offset = videoSource.time_offset_ms ?? 0;
    const targetMs = Math.max(offset, Math.round(requestedMs));
    // +1 ms keeps the seek inside the requested frame despite rounding of time_ms.
    video.currentTime = (targetMs - offset + 1) / 1000;
    setTimeInput(String(targetMs));
    setFrameCopyStatus("idle");
    return video;
  };

  const setVideoFrame = (requestedFrame: number): HTMLVideoElement | null => {
    const video = videoRef.current;
    if (!video || !videoSource) return null;

    const maxFrame = Number.isFinite(video.duration)
      ? Math.max(0, Math.ceil(video.duration * videoSource.fps) - 1)
      : Number.POSITIVE_INFINITY;
    const targetFrame = Math.min(Math.max(0, Math.round(requestedFrame)), maxFrame);
    video.currentTime = targetFrame / videoSource.fps;
    setFrameInput(String(targetFrame));
    setFrameCopyStatus("idle");
    return video;
  };

  const seekKeyframe = () =>
    keyframeTimeMs !== null ? setVideoTimeMs(keyframeTimeMs) : setVideoFrame(result.frame_id);

  const playFromKeyframe = () => {
    const video = seekKeyframe();
    if (!video) return;
    void video.play().catch(() => undefined);
  };

  const pauseAtKeyframe = () => {
    const video = seekKeyframe();
    video?.pause();
  };

  const updatePlayingFrame = () => {
    const video = videoRef.current;
    if (!video || !videoSource || document.activeElement === frameInputRef.current) return;
    if (timeMode) {
      setTimeInput(
        String(Math.round(video.currentTime * 1000) + (videoSource.time_offset_ms ?? 0)),
      );
    } else {
      setFrameInput(String(Math.max(0, Math.round(video.currentTime * videoSource.fps))));
    }
    setFrameCopyStatus("idle");
  };

  const navigateToFrame = (frame: number) => {
    const video = setVideoFrame(frame);
    video?.pause();
  };

  const commitFrameInput = () => {
    if (timeMode) {
      const parsedMs = Number(timeInput);
      if (Number.isFinite(parsedMs)) setVideoTimeMs(parsedMs)?.pause();
      else updatePlayingFrame();
      return;
    }
    const parsedFrame = Number(frameInput);
    if (Number.isFinite(parsedFrame)) {
      navigateToFrame(parsedFrame);
    } else {
      updatePlayingFrame();
    }
  };

  const stepFrame = (offset: number) => {
    if (timeMode && videoSource) {
      // VFR: step by one average frame duration.
      const parsedMs = Number(timeInput);
      const base = Number.isFinite(parsedMs) ? parsedMs : (keyframeTimeMs ?? 0);
      setVideoTimeMs(base + offset * Math.round(1000 / videoSource.fps))?.pause();
      return;
    }
    const video = videoRef.current;
    const currentFrame = Number(frameInput);
    const fallbackFrame = video && videoSource
      ? Math.round(video.currentTime * videoSource.fps)
      : result.frame_id;
    navigateToFrame((Number.isFinite(currentFrame) ? currentFrame : fallbackFrame) + offset);
  };

  // Moving to another keyframe keeps the player open and seeks it there.
  const shownKeyframeRef = useRef({ frameId: result.frame_id, timeMs: keyframeTimeMs });
  useEffect(() => {
    const shown = shownKeyframeRef.current;
    if (shown.frameId === result.frame_id && shown.timeMs === keyframeTimeMs) return;
    shownKeyframeRef.current = { frameId: result.frame_id, timeMs: keyframeTimeMs };
    setFrameInput(String(result.frame_id));
    setTimeInput(String(keyframeTimeMs ?? ""));
    setCopyStatus("idle");
    seekKeyframe()?.pause();
  });

  const stepKeyframe = (offset: number) => {
    const next = neighbours.keyframes[neighbours.centerIndex + offset];
    if (onNavigate && neighbours.centerIndex >= 0 && next) onNavigate(next);
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.altKey || event.ctrlKey || event.metaKey || isTypingTarget(event.target)) return;
      event.preventDefault();
      const offset = event.key === "ArrowLeft" ? -1 : 1;
      // Shift moves keyframe by keyframe even while the video is open.
      if (videoSource && !event.shiftKey) stepFrame(offset);
      else stepKeyframe(offset);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  });

  const copyCurrentFrame = async () => {
    try {
      await navigator.clipboard.writeText(timeMode ? timeInput : frameInput);
      setFrameCopyStatus("copied");
    } catch {
      setFrameCopyStatus("failed");
    }
  };

  const copyVideoAndFrame = async () => {
    try {
      await navigator.clipboard.writeText(`${result.video_id}\t${result.frame_id}`);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  };

  return createPortal(
    <div className="modal-backdrop" onMouseDown={closeOnBackdrop}>
      <section
        ref={dialogRef}
        className="detail"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-modal-title"
        tabIndex={-1}
      >
        <header className="detail__head">
          <div className="detail__identity">
            <h2 id="detail-modal-title">
              <span className="detail__video">{result.video_id}</span>
              <span className="detail__frame">
                {keyframeTimeMs !== null
                  ? `${formatMs(keyframeTimeMs)} (${keyframeTimeMs} ms)`
                  : `frame ${result.frame_id}`}
              </span>
            </h2>
            {result.camera_name && (
              <p className="detail__traffic">
                {[result.camera_name, result.clock_time, result.weather === "wet" ? "mưa/ướt" : null]
                  .filter(Boolean)
                  .join(", ")}
              </p>
            )}
            <button
              type="button"
              className="button button--text"
              onClick={copyVideoAndFrame}
              aria-label="Sao chép mã video và frame"
            >
              {copyStatus === "copied"
                ? "Đã chép"
                : copyStatus === "failed"
                  ? "Không chép được"
                  : "Sao chép"}
            </button>
          </div>
          <div className="detail__actions">
            {videoSource && (
              <button type="button" className="button button--quiet" onClick={pauseAtKeyframe}>
                Về keyframe
              </button>
            )}
            <button
              type="button"
              className="button button--quiet"
              onClick={toggleVideo}
              disabled={videoStatus === "loading"}
            >
              {videoStatus === "loading"
                ? "Đang tải video…"
                : videoSource
                  ? "Xem keyframe"
                  : "Phát video"}
            </button>
            {submitTarget && (
              <button
                type="button"
                className="button button--primary"
                onClick={() => setShowSubmit((open) => !open)}
                aria-expanded={showSubmit}
              >
                Nộp DRES
              </button>
            )}
            <button
              ref={closeButtonRef}
              className="button button--icon"
              type="button"
              onClick={onClose}
              aria-label="Đóng"
            >
              ×
            </button>
          </div>
        </header>

        <div className="detail__body">
          <div className="detail__viewer">
            <div className="detail__media">
              {videoSource ? (
                <video
                  ref={videoRef}
                  className="detail__video-player"
                  src={resolveMediaUrl(videoSource.url)}
                  controls
                  autoPlay
                  preload="metadata"
                  onLoadedMetadata={playFromKeyframe}
                  onTimeUpdate={updatePlayingFrame}
                >
                  Trình duyệt không phát được video này.
                </video>
              ) : (
                <ResultImage
                  src={result.keyframe_url}
                  alt={`Keyframe ${result.frame_id} của ${result.video_id}`}
                  className="detail__image"
                  eager
                />
              )}
              {videoStatus === "error" && (
                <p className="detail__media-error" role="alert">
                  Không tìm thấy video này ở máy local lẫn nguồn từ xa.
                </p>
              )}
            </div>

            {videoSource && (
              <div className="frame-nav">
                <input
                  ref={frameInputRef}
                  type="number"
                  min="0"
                  step="1"
                  value={timeMode ? timeInput : frameInput}
                  aria-label={timeMode ? "Thời điểm hiện tại (ms)" : "Frame hiện tại"}
                  title={timeMode ? "Thời gian gốc (ms)" : undefined}
                  onChange={(event) => {
                    if (timeMode) setTimeInput(event.target.value);
                    else setFrameInput(event.target.value);
                    setFrameCopyStatus("idle");
                  }}
                  onBlur={commitFrameInput}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") commitFrameInput();
                  }}
                />
                <button
                  type="button"
                  onClick={() => stepFrame(-1)}
                  aria-label="Frame trước"
                >
                  −
                </button>
                <button
                  type="button"
                  onClick={() => stepFrame(1)}
                  aria-label="Frame sau"
                >
                  +
                </button>
                <button
                  type="button"
                  className="frame-nav__copy"
                  onClick={copyCurrentFrame}
                  aria-label="Sao chép frame hiện tại"
                >
                  {frameCopyStatus === "copied"
                    ? "Đã chép"
                    : frameCopyStatus === "failed"
                      ? "Không chép được"
                      : "Sao chép"}
                </button>
              </div>
            )}

            {onNavigate && (
              <TemporalStrip
                keyframes={neighbours.keyframes}
                currentFrameId={result.frame_id}
                isLoading={neighbours.query.isPending}
                isError={neighbours.query.isError}
                onSelect={onNavigate}
              />
            )}
          </div>

          <div className="detail__side">
            {submitTarget && showSubmit && (
              <DresSubmitPanel
                target={submitTarget}
                currentFrame={currentFrame}
                currentTimeMs={currentTimeMs}
                onCancel={() => setShowSubmit(false)}
              />
            )}

            <section className="detail__section" aria-labelledby="asr-heading">
              <h3 id="asr-heading">Lời thoại (ASR)</h3>
              <p className={result.asr_text ? undefined : "detail__empty"}>
                {result.asr_text || "Shot này không có lời thoại."}
              </p>
            </section>

            {result.objects.length > 0 && (
              <section className="detail__section" aria-labelledby="objects-heading">
                <h3 id="objects-heading">Object nhận diện được</h3>
                <ul className="object-list">
                  {result.objects.map((object, index) => (
                    <li key={`${String(object.label ?? "object")}-${index}`}>
                      {String(object.label ?? `Object ${index + 1}`)}
                      {typeof object.count === "number" && object.count > 1 && (
                        <span>×{object.count}</span>
                      )}
                      {typeof object.score === "number" && (
                        <span>{formatScore(object.score)}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        </div>
      </section>
    </div>,
    document.body,
  );
}
