import { type MouseEvent, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { ResultImage } from "./ResultImage";
import { useModalAccessibility } from "./useModalAccessibility";

export interface ResultDetail {
  video_id: string;
  frame_id: number;
  keyframe_url: string;
  segment_id: string;
  asr_text: string;
  ocr_text: string;
  objects: Record<string, unknown>[];
  similarity_score: number;
}

interface ResultDetailModalProps {
  result: ResultDetail;
  onClose: () => void;
}

export function formatScore(score: number): string {
  return score.toFixed(4);
}

export function ResultDetailModal({ result, onClose }: ResultDetailModalProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  useModalAccessibility({ dialogRef, initialFocusRef: closeButtonRef, onClose });
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");

  const closeOnBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  const openVideoInExplorer = async () => {
    try {
      const response = await fetch(`/api/v1/search/open-video/${result.video_id}`, { method: "POST" });
      if (!response.ok) {
        if (response.status === 404) {
          alert("Video has not been downloaded yet.");
        } else {
          alert("Failed to open video locally.");
        }
      }
    } catch (e) {
      alert("Failed to connect to backend to open video.");
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
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <button 
              type="button" 
              onClick={openVideoInExplorer}
              className="button"
              style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem', borderRadius: '0.4rem', border: '1px solid #c8d3cb', background: '#f1f5f2', cursor: 'pointer' }}
            >
              📂 Open Local Video
            </button>
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
          <div className="detail-modal__media">
            <ResultImage
              src={result.keyframe_url}
              alt={`Keyframe ${result.frame_id} from ${result.video_id}`}
              className="detail-modal__image"
              eager
            />
          </div>

          <div className="detail-modal__content">
            <section className="detail-section" aria-labelledby="asr-heading">
              <h3 id="asr-heading">ASR transcript</h3>
              <p>{result.asr_text || "No ASR transcript available."}</p>
            </section>

            {result.ocr_text && (
              <section className="detail-section" aria-labelledby="ocr-heading">
                <h3 id="ocr-heading">OCR text</h3>
                <p>{result.ocr_text}</p>
              </section>
            )}

            {result.objects.length > 0 && (
              <section className="detail-section" aria-labelledby="objects-heading">
                <h3 id="objects-heading">Detected objects</h3>
                <ul className="object-list">
                  {result.objects.map((object, index) => (
                    <li key={`${String(object.label ?? "object")}-${index}`}>
                      {String(object.label ?? `Object ${index + 1}`)}
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
