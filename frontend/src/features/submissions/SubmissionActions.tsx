import { type MouseEvent, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  downloadSubmission,
  friendlySubmissionError,
  renderSubmission,
} from "../../api/client";
import type { SubmissionRenderResponse, SubmissionRequest } from "../../api/types";

interface SubmissionActionsProps {
  queryType: SubmissionRequest["query_type"];
  rowCount: number;
  emptyAnswerCount?: number;
  orderChanged: boolean;
  onResetOrder: () => void;
  buildPayload: (filename: string) => SubmissionRequest;
}

const DEFAULT_FILENAMES: Record<SubmissionRequest["query_type"], string> = {
  KIS: "kis_submission.csv",
  VQA: "vqa_submission.csv",
  TRAKE: "trake_submission.csv",
};

export function SubmissionActions({
  queryType,
  rowCount,
  emptyAnswerCount = 0,
  orderChanged,
  onResetOrder,
  buildPayload,
}: SubmissionActionsProps) {
  const [filename, setFilename] = useState(DEFAULT_FILENAMES[queryType]);
  const [preview, setPreview] = useState<SubmissionRenderResponse | null>(null);
  const [finalFilename, setFinalFilename] = useState<string | null>(null);
  const [previewPending, setPreviewPending] = useState(false);
  const [downloadPending, setDownloadPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setFilename(DEFAULT_FILENAMES[queryType]);
    setPreview(null);
    setFinalFilename(null);
  }, [queryType]);

  const previewSubmission = async () => {
    setPreviewPending(true);
    setError(null);
    try {
      const response = await renderSubmission(buildPayload(filename));
      setPreview(response);
      setFinalFilename(response.filename);
    } catch (requestError) {
      setError(requestError);
    } finally {
      setPreviewPending(false);
    }
  };

  const downloadCurrentSubmission = async () => {
    setDownloadPending(true);
    setError(null);
    try {
      const { blob, filename: downloadedFilename } = await downloadSubmission(
        buildPayload(filename),
      );
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = downloadedFilename;
      anchor.click();
      URL.revokeObjectURL(objectUrl);
      setFinalFilename(downloadedFilename);
    } catch (requestError) {
      setError(requestError);
    } finally {
      setDownloadPending(false);
    }
  };

  return (
    <aside className="submission-bar" aria-label="Submission actions">
      <div className="submission-bar__summary">
        <strong>{rowCount} rows</strong>
        <span>{queryType} submission</span>
        {emptyAnswerCount > 0 && (
          <span className="submission-warning" role="status">
            {emptyAnswerCount} empty VQA answer{emptyAnswerCount === 1 ? "" : "s"}
          </span>
        )}
      </div>

      <label className="submission-filename" htmlFor={`submission-filename-${queryType}`}>
        <span>Filename</span>
        <input
          id={`submission-filename-${queryType}`}
          value={filename}
          maxLength={255}
          onChange={(event) => {
            setFilename(event.target.value);
            setFinalFilename(null);
          }}
        />
      </label>

      <div className="submission-bar__actions">
        <button
          type="button"
          className="secondary-button"
          disabled={!orderChanged}
          onClick={onResetOrder}
        >
          Reset order
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={previewPending}
          onClick={() => void previewSubmission()}
        >
          {previewPending ? "Preparing preview…" : "Preview submission"}
        </button>
        <button
          type="button"
          className="submission-download-button"
          disabled={downloadPending}
          onClick={() => void downloadCurrentSubmission()}
        >
          {downloadPending ? "Downloading…" : "Download submission"}
        </button>
      </div>

      {finalFilename && (
        <p className="submission-final-filename" role="status">
          Backend filename: <strong>{finalFilename}</strong>
        </p>
      )}
      {error !== null && (
        <p className="submission-error" role="alert">
          {friendlySubmissionError(error)}
        </p>
      )}

      {preview && (
        <SubmissionPreviewModal
          preview={preview}
          onClose={() => setPreview(null)}
        />
      )}
    </aside>
  );
}

interface SubmissionPreviewModalProps {
  preview: SubmissionRenderResponse;
  onClose: () => void;
}

function SubmissionPreviewModal({ preview, onClose }: SubmissionPreviewModalProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(onClose, [onClose]);
  useEffect(() => {
    closeButtonRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [close]);

  const closeOnBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) close();
  };

  return createPortal(
    <div className="modal-backdrop" onMouseDown={closeOnBackdrop}>
      <section
        className="submission-preview-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="submission-preview-title"
      >
        <header className="detail-modal__header">
          <div>
            <p className="eyebrow eyebrow--dark">Backend-rendered CSV</p>
            <h2 id="submission-preview-title">{preview.filename}</h2>
          </div>
          <button
            ref={closeButtonRef}
            className="modal-close"
            type="button"
            onClick={close}
            aria-label="Close submission preview"
          >
            ×
          </button>
        </header>
        <div className="submission-preview-modal__body">
          <div className="submission-preview-meta">
            <strong>{preview.row_count} rows</strong>
            <span>UTF-8 CSV · no header</span>
          </div>
          {preview.warnings.length > 0 && (
            <ul className="submission-preview-warnings" aria-label="Submission warnings">
              {preview.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <pre data-testid="submission-preview-content">{preview.content}</pre>
        </div>
      </section>
    </div>,
    document.body,
  );
}
