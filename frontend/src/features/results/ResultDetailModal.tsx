import { type MouseEvent, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { getVideoSource, resolveMediaUrl } from "../../api/client";
import type { VideoSourceResponse } from "../../api/types";
import { DresSubmitPanel, type SubmitTarget } from "../submission/DresSubmitPanel";
import { ResultImage } from "./ResultImage";
import { useModalAccessibility } from "./useModalAccessibility";

export interface ResultDetail {
  video_id: string;
  frame_id: number;
  keyframe_url: string;
  segment_id: string;
  asr_text: string;
  objects: Record<string, unknown>[];
  similarity_score: number;
}

interface ResultDetailModalProps {
  result: ResultDetail;
  onClose: () => void;
  /** When set, the modal offers a DRES submission for this result. */
  submitTarget?: SubmitTarget;
}

export function formatScore(score: number): string {
  return score.toFixed(4);
}

export function ResultDetailModal({ result, onClose, submitTarget }: ResultDetailModalProps) {
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
  const parsedFrameInput = Number(frameInput);
  const currentFrame =
    videoSource && frameInput.trim() !== "" && Number.isInteger(parsedFrameInput)
      ? parsedFrameInput
      : null;

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

  const playFromKeyframe = () => {
    const video = setVideoFrame(result.frame_id);
    if (!video) return;
    void video.play().catch(() => undefined);
  };

  const pauseAtKeyframe = () => {
    const video = setVideoFrame(result.frame_id);
    video?.pause();
  };

  const updatePlayingFrame = () => {
    const video = videoRef.current;
    if (!video || !videoSource || document.activeElement === frameInputRef.current) return;
    setFrameInput(String(Math.max(0, Math.round(video.currentTime * videoSource.fps))));
    setFrameCopyStatus("idle");
  };

  const navigateToFrame = (frame: number) => {
    const video = setVideoFrame(frame);
    video?.pause();
  };

  const commitFrameInput = () => {
    const parsedFrame = Number(frameInput);
    if (Number.isFinite(parsedFrame)) {
      navigateToFrame(parsedFrame);
    } else {
      updatePlayingFrame();
    }
  };

  const stepFrame = (offset: number) => {
    const video = videoRef.current;
    const currentFrame = Number(frameInput);
    const fallbackFrame = video && videoSource
      ? Math.round(video.currentTime * videoSource.fps)
      : result.frame_id;
    navigateToFrame((Number.isFinite(currentFrame) ? currentFrame : fallbackFrame) + offset);
  };

  const copyCurrentFrame = async () => {
    try {
      await navigator.clipboard.writeText(frameInput);
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
        className="detail-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-modal-title"
        tabIndex={-1}
      >
        <header className="detail-modal__header">
          <div className="detail-modal__identity">
            <h2 id="detail-modal-title">
              <span>{result.video_id}</span>
              <span className="detail-modal__separator" aria-hidden="true">•</span>
              <span className="detail-modal__frame">{result.frame_id}</span>
            </h2>
            <button
              type="button"
              className="detail-copy-button"
              onClick={copyVideoAndFrame}
              aria-label="Copy video ID and frame"
            >
              {copyStatus === "copied"
                ? "Copied"
                : copyStatus === "failed"
                  ? "Copy failed"
                  : "Copy"}
            </button>
          </div>
          <div className="detail-modal__header-actions">
            {submitTarget && (
              <button
                type="button"
                onClick={() => setShowSubmit((open) => !open)}
                aria-expanded={showSubmit}
                className="detail-keyframe-action detail-submit-action"
              >
                Submit DRES
              </button>
            )}
            <button
              type="button"
              onClick={toggleVideo}
              disabled={videoStatus === "loading"}
              className="detail-keyframe-action detail-keyframe-action--toggle"
            >
              {videoStatus === "loading"
                ? "Loading video…"
                : videoSource
                  ? "Show keyframe"
                  : "Play from keyframe"}
            </button>
            {videoSource && (
              <button
                type="button"
                onClick={pauseAtKeyframe}
                className="detail-keyframe-action detail-keyframe-action--return"
              >
                Back to keyframe
              </button>
            )}
            <button
              ref={closeButtonRef}
              className="modal-close"
              type="button"
              onClick={onClose}
              aria-label="Close keyframe detail"
            >
              ×
            </button>
          </div>
        </header>

        <div className="detail-modal__body">
          <div className="detail-modal__viewer">
            <div className="detail-modal__media">
              {videoSource ? (
                <video
                  ref={videoRef}
                  className="detail-modal__video"
                  src={resolveMediaUrl(videoSource.url)}
                  controls
                  autoPlay
                  preload="metadata"
                  onLoadedMetadata={playFromKeyframe}
                  onTimeUpdate={updatePlayingFrame}
                >
                  Your browser does not support video playback.
                </video>
              ) : (
                <ResultImage
                  src={result.keyframe_url}
                  alt={`Keyframe ${result.frame_id} from ${result.video_id}`}
                  className="detail-modal__image"
                  eager
                />
              )}
              {videoStatus === "error" && (
                <p className="detail-modal__video-error" role="alert">
                  Video is unavailable from both local and remote sources.
                </p>
              )}
            </div>

            {videoSource && (
              <div className="detail-frame-navigation">
                <input
                  ref={frameInputRef}
                  type="number"
                  min="0"
                  step="1"
                  value={frameInput}
                  aria-label="Current frame ID"
                  onChange={(event) => {
                    setFrameInput(event.target.value);
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
                  aria-label="Previous frame"
                >
                  −
                </button>
                <button
                  type="button"
                  onClick={() => stepFrame(1)}
                  aria-label="Next frame"
                >
                  +
                </button>
                <button
                  type="button"
                  className="detail-frame-copy"
                  onClick={copyCurrentFrame}
                  aria-label="Copy current frame ID"
                >
                  {frameCopyStatus === "copied"
                    ? "Copied"
                    : frameCopyStatus === "failed"
                      ? "Copy failed"
                      : "Copy"}
                </button>
              </div>
            )}
          </div>

          <div className="detail-modal__content">
            {submitTarget && showSubmit && (
              <DresSubmitPanel
                target={submitTarget}
                currentFrame={currentFrame}
                onCancel={() => setShowSubmit(false)}
              />
            )}

            <section className="detail-section" aria-labelledby="asr-heading">
              <h3 id="asr-heading">ASR transcript</h3>
              <p>{result.asr_text || "No ASR transcript available."}</p>
            </section>

            {result.objects.length > 0 && (
              <section className="detail-section" aria-labelledby="objects-heading">
                <h3 id="objects-heading">Detected objects</h3>
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
