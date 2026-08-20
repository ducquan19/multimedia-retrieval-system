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
  const [isVideoPlaying, setIsVideoPlaying] = useState(false);

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
          <div>
            <p className="eyebrow eyebrow--dark">Keyframe detail</p>
            <h2 id="detail-modal-title">{result.video_id}</h2>
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
            <dl className="detail-metadata">
              <div>
                <dt>Video ID</dt>
                <dd>{result.video_id}</dd>
              </div>
              <div>
                <dt>Frame ID</dt>
                <dd>{result.frame_id}</dd>
              </div>
              <div>
                <dt>Segment</dt>
                <dd>{result.segment_id || "Not available"}</dd>
              </div>
              <div>
                <dt>Similarity</dt>
                <dd>{formatScore(result.similarity_score)}</dd>
              </div>
            </dl>

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
