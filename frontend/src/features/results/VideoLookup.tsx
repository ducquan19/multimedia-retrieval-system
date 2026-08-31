import {
  type ClipboardEvent,
  type FormEvent,
  type MouseEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { getVideoSource, resolveMediaUrl } from "../../api/client";
import type { VideoSourceResponse } from "../../api/types";
import { useModalAccessibility } from "./useModalAccessibility";

export function VideoLookup() {
  const [videoId, setVideoId] = useState("");
  const [frameId, setFrameId] = useState("");
  const [openedVideo, setOpenedVideo] = useState<{
    videoId: string;
    frameId: number;
  } | null>(null);

  const parsedFrameId = parseFrameId(frameId);

  const openVideo = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedVideoId = videoId.trim();
    if (normalizedVideoId && parsedFrameId !== null) {
      setOpenedVideo({ videoId: normalizedVideoId, frameId: parsedFrameId });
    }
  };

  const pasteVideoAndFrame = (event: ClipboardEvent<HTMLFormElement>) => {
    const firstRow = event.clipboardData.getData("text").split(/\r?\n/, 1)[0] ?? "";
    const cells = firstRow.split("\t");
    if (cells.length < 2) return;

    const pastedVideoId = cells[0]?.trim() ?? "";
    const pastedFrameId = cells[1]?.trim() ?? "";
    if (!pastedVideoId || parseFrameId(pastedFrameId) === null) return;

    event.preventDefault();
    setVideoId(pastedVideoId);
    setFrameId(pastedFrameId);
  };

  return (
    <>
      <form
        className="video-lookup"
        aria-label="Open video by ID and frame"
        onSubmit={openVideo}
        onPaste={pasteVideoAndFrame}
      >
        <input
          className="video-lookup__video-id"
          type="text"
          value={videoId}
          onChange={(event) => setVideoId(event.target.value)}
          aria-label="Video ID"
          placeholder="video_id"
          autoCapitalize="none"
          autoComplete="off"
          spellCheck={false}
        />
        <input
          className="video-lookup__frame-id"
          type="number"
          min="0"
          step="1"
          value={frameId}
          onChange={(event) => setFrameId(event.target.value)}
          aria-label="Frame ID"
          placeholder="frame_id"
          autoComplete="off"
        />
        <button type="submit" disabled={!videoId.trim() || parsedFrameId === null}>
          Open
        </button>
      </form>

      {openedVideo && (
        <VideoPlayerModal
          key={`${openedVideo.videoId}:${openedVideo.frameId}`}
          videoId={openedVideo.videoId}
          initialFrameId={openedVideo.frameId}
          onClose={() => setOpenedVideo(null)}
        />
      )}
    </>
  );
}

function parseFrameId(value: string): number | null {
  if (!value.trim()) return 0;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

interface VideoPlayerModalProps {
  videoId: string;
  initialFrameId: number;
  onClose: () => void;
}

function VideoPlayerModal({ videoId, initialFrameId, onClose }: VideoPlayerModalProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameInputRef = useRef<HTMLInputElement>(null);
  const [videoSource, setVideoSource] = useState<VideoSourceResponse | null>(null);
  const [videoStatus, setVideoStatus] = useState<"loading" | "ready" | "error">("loading");
  const [frameInput, setFrameInput] = useState(String(initialFrameId));
  const [frameCopyStatus, setFrameCopyStatus] = useState<"idle" | "copied" | "failed">("idle");

  useModalAccessibility({ dialogRef, initialFocusRef: closeButtonRef, onClose });

  useEffect(() => {
    const controller = new AbortController();
    setVideoStatus("loading");
    getVideoSource(videoId, controller.signal)
      .then((source) => {
        setVideoSource(source);
        setVideoStatus("ready");
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setVideoStatus("error");
      });
    return () => controller.abort();
  }, [videoId]);

  const closeOnBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  const setVideoFrame = (requestedFrame: number, pauseAfterSeek = true) => {
    const video = videoRef.current;
    if (!video || !videoSource) return;

    const maxFrame = Number.isFinite(video.duration)
      ? Math.max(0, Math.ceil(video.duration * videoSource.fps) - 1)
      : Number.POSITIVE_INFINITY;
    const targetFrame = Math.min(Math.max(0, Math.round(requestedFrame)), maxFrame);
    video.currentTime = targetFrame / videoSource.fps;
    if (pauseAfterSeek) video.pause();
    setFrameInput(String(targetFrame));
    setFrameCopyStatus("idle");
  };

  const updatePlayingFrame = () => {
    const video = videoRef.current;
    if (!video || !videoSource || document.activeElement === frameInputRef.current) return;
    setFrameInput(String(Math.max(0, Math.round(video.currentTime * videoSource.fps))));
    setFrameCopyStatus("idle");
  };

  const commitFrameInput = () => {
    const parsedFrame = Number(frameInput);
    if (Number.isFinite(parsedFrame)) {
      setVideoFrame(parsedFrame);
    } else {
      updatePlayingFrame();
    }
  };

  const stepFrame = (offset: number) => {
    const video = videoRef.current;
    const parsedFrame = Number(frameInput);
    const currentFrame = Number.isFinite(parsedFrame)
      ? parsedFrame
      : video && videoSource
        ? Math.round(video.currentTime * videoSource.fps)
        : 0;
    setVideoFrame(currentFrame + offset);
  };

  const copyCurrentFrame = async () => {
    try {
      await navigator.clipboard.writeText(frameInput);
      setFrameCopyStatus("copied");
    } catch {
      setFrameCopyStatus("failed");
    }
  };

  return createPortal(
    <div className="modal-backdrop" onMouseDown={closeOnBackdrop}>
      <section
        ref={dialogRef}
        className="detail-modal video-player-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="video-player-modal-title"
        tabIndex={-1}
      >
        <header className="detail-modal__header">
          <h2 id="video-player-modal-title">{videoId}</h2>
          <button
            ref={closeButtonRef}
            className="modal-close"
            type="button"
            onClick={onClose}
            aria-label="Close video player"
          >
            ×
          </button>
        </header>

        <div className="detail-modal__body">
          <div className="detail-modal__viewer">
            <div className="detail-modal__media">
              {videoStatus === "loading" && (
                <p className="video-player-modal__status" role="status">Loading video…</p>
              )}
              {videoSource && (
                <video
                  ref={videoRef}
                  className="detail-modal__video"
                  src={resolveMediaUrl(videoSource.url)}
                  controls
                  autoPlay
                  preload="metadata"
                  onLoadedMetadata={() => setVideoFrame(initialFrameId, false)}
                  onTimeUpdate={updatePlayingFrame}
                >
                  Your browser does not support video playback.
                </video>
              )}
              {videoStatus === "error" && (
                <p className="detail-modal__video-error" role="alert">
                  Video is unavailable from both local and remote sources.
                </p>
              )}
            </div>

            <div className="detail-frame-navigation">
              <input
                ref={frameInputRef}
                type="number"
                min="0"
                step="1"
                value={frameInput}
                disabled={!videoSource}
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
                disabled={!videoSource}
                onClick={() => stepFrame(-1)}
                aria-label="Previous frame"
              >
                −
              </button>
              <button
                type="button"
                disabled={!videoSource}
                onClick={() => stepFrame(1)}
                aria-label="Next frame"
              >
                +
              </button>
              <button
                type="button"
                className="detail-frame-copy"
                disabled={!videoSource}
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
          </div>
        </div>
      </section>
    </div>,
    document.body,
  );
}
