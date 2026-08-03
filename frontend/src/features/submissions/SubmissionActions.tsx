import { type MouseEvent, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  downloadSubmission,
  friendlySubmissionError,
  renderSubmission,
} from "../../api/client";
import type { SubmissionRenderResponse, SubmissionRequest } from "../../api/types";
import { useModalAccessibility } from "../results/useModalAccessibility";

interface SubmissionActionsProps {
  queryType: SubmissionRequest["query_type"];
  rowCount: number;
  emptyAnswerCount?: number;
  orderChanged: boolean;
  stateVersion: string;
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
  stateVersion,
  onResetOrder,
  buildPayload,
}: SubmissionActionsProps) {
  const [filename, setFilename] = useState(DEFAULT_FILENAMES[queryType]);
  const [preview, setPreview] = useState<SubmissionRenderResponse | null>(null);
  const [finalFilename, setFinalFilename] = useState<string | null>(null);
  const [previewPending, setPreviewPending] = useState(false);
  const [downloadPending, setDownloadPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const previewController = useRef<AbortController | null>(null);
  const downloadController = useRef<AbortController | null>(null);
  const closePreview = useCallback(() => setPreview(null), []);

  useEffect(() => {
    setFilename(DEFAULT_FILENAMES[queryType]);
  }, [queryType]);

  useEffect(() => {
    previewController.current?.abort();
    downloadController.current?.abort();
    previewController.current = null;
    downloadController.current = null;
    setPreview(null);
    setFinalFilename(null);
    setPreviewPending(false);
    setDownloadPending(false);
    setError(null);
  }, [stateVersion]);

  useEffect(
    () => () => {
      previewController.current?.abort();
      downloadController.current?.abort();
    },
    [],
  );

  const previewSubmission = async () => {
    previewController.current?.abort();
    const controller = new AbortController();
    previewController.current = controller;
    setPreviewPending(true);
    setError(null);
    try {
      const response = await renderSubmission(buildPayload(filename), controller.signal);
      if (previewController.current !== controller) return;
      setPreview(response);
      setFinalFilename(response.filename);
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") return;
      setError(requestError);
    } finally {
      if (previewController.current === controller) {
        previewController.current = null;
        setPreviewPending(false);
      }
    }
  };

  const downloadCurrentSubmission = async () => {
    downloadController.current?.abort();
    const controller = new AbortController();
    downloadController.current = controller;
    setDownloadPending(true);
    setError(null);
    try {
      const { blob, filename: downloadedFilename } = await downloadSubmission(
        buildPayload(filename),
        controller.signal,
      );
      if (downloadController.current !== controller) return;
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = downloadedFilename;
      anchor.click();
      URL.revokeObjectURL(objectUrl);
      setFinalFilename(downloadedFilename);
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === "AbortError") return;
      setError(requestError);
    } finally {
      if (downloadController.current === controller) {
        downloadController.current = null;
        setDownloadPending(false);
      }
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
            previewController.current?.abort();
            downloadController.current?.abort();
            previewController.current = null;
            downloadController.current = null;
            setPreviewPending(false);
            setDownloadPending(false);
            setFilename(event.target.value);
            setPreview(null);
            setFinalFilename(null);
            setError(null);
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
          onClose={closePreview}
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
  const dialogRef = useRef<HTMLElement>(null);
  useModalAccessibility({ dialogRef, initialFocusRef: closeButtonRef, onClose });

  const closeOnBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  return createPortal(
    <div className="modal-backdrop" onMouseDown={closeOnBackdrop}>
      <section
        ref={dialogRef}
        className="submission-preview-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="submission-preview-title"
        tabIndex={-1}
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
            onClick={onClose}
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
