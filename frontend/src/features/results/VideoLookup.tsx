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
import { DresSubmitPanel } from "../submission/DresSubmitPanel";
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
        aria-label="Mở video theo mã và frame"
        onSubmit={openVideo}
        onPaste={pasteVideoAndFrame}
      >
        <input
          className="video-lookup__video-id"
          type="text"
          value={videoId}
          onChange={(event) => setVideoId(event.target.value)}
          aria-label="Mã video"
          placeholder="Mã video"
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
          aria-label="Frame"
          placeholder="Frame"
          autoComplete="off"
        />
        <button
          type="submit"
          className="button button--quiet"
          disabled={!videoId.trim() || parsedFrameId === null}
        >
          Mở video
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
  // Frame the submission starts from: the one on screen when "Submit DRES" was opened.
  const [submitFrame, setSubmitFrame] = useState<number | null>(null);
  const parsedFrameInput = Number(frameInput);
  const currentFrame =
    videoSource && frameInput.trim() !== "" && Number.isInteger(parsedFrameInput)
      ? parsedFrameInput
      : null;

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

  const setVideoFrame = (requestedFrame: number) => {
    const video = videoRef.current;
    if (!video || !videoSource) return;

    const maxFrame = Number.isFinite(video.duration)
      ? Math.max(0, Math.ceil(video.duration * videoSource.fps) - 1)
      : Number.POSITIVE_INFINITY;
    const targetFrame = Math.min(Math.max(0, Math.round(requestedFrame)), maxFrame);
    video.currentTime = targetFrame / videoSource.fps;
    video.pause();
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
        className={`detail detail--player${submitFrame !== null ? " detail--submitting" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="video-player-modal-title"
        tabIndex={-1}
      >
        <header className="detail__head">
          <div className="detail__identity">
            <h2 id="video-player-modal-title">
              <span className="detail__video">{videoId}</span>
            </h2>
          </div>
          <div className="detail__actions">
            <button
              type="button"
              className="button button--primary"
              aria-expanded={submitFrame !== null}
              disabled={!videoSource}
              onClick={() =>
                setSubmitFrame((open) => (open === null ? (currentFrame ?? initialFrameId) : null))
              }
            >
              Nộp DRES
            </button>
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
              {videoStatus === "loading" && (
                <p className="detail__media-status" role="status">
                  Đang tải video…
                </p>
              )}
              {videoSource && (
                <video
                  ref={videoRef}
                  className="detail__video-player"
                  src={resolveMediaUrl(videoSource.url)}
                  controls
                  preload="metadata"
                  onLoadedMetadata={() => setVideoFrame(initialFrameId)}
                  onTimeUpdate={updatePlayingFrame}
                >
                  Trình duyệt không phát được video này.
                </video>
              )}
              {videoStatus === "error" && (
                <p className="detail__media-error" role="alert">
                  Không tìm thấy video này ở máy local lẫn nguồn từ xa.
                </p>
              )}
            </div>

            <div className="frame-nav">
              <input
                ref={frameInputRef}
                type="number"
                min="0"
                step="1"
                value={frameInput}
                disabled={!videoSource}
                aria-label="Frame hiện tại"
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
                aria-label="Frame trước"
              >
                −
              </button>
              <button
                type="button"
                disabled={!videoSource}
                onClick={() => stepFrame(1)}
                aria-label="Frame sau"
              >
                +
              </button>
              <button
                type="button"
                className="frame-nav__copy"
                disabled={!videoSource}
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
          </div>

          {submitFrame !== null && (
            <div className="detail__side">
              <DresSubmitPanel
                target={{
                  kind: "single",
                  videoId,
                  frameId: submitFrame,
                  defaultMode: "KIS",
                  answer: "",
                  allowTrake: true,
                }}
                currentFrame={currentFrame}
                onCancel={() => setSubmitFrame(null)}
              />
            </div>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}
