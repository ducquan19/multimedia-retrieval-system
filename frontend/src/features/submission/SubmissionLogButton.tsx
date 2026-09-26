import { useEffect, useRef, useState } from "react";

import { clearSubmissionLog, entryTone, formatClock, useSubmissionLog } from "./submissionLog";

export function SubmissionLogButton() {
  const entries = useSubmissionLog();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className="submission-log" ref={containerRef}>
      <button
        type="button"
        className="submission-log__toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        Đã nộp <span className="submission-log__count">{entries.length}</span>
      </button>
      {open && (
        <section className="submission-log__panel" aria-label="Submission log">
          <header>
            <strong>Nhật ký nộp DRES</strong>
            {entries.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  if (window.confirm("Xóa toàn bộ nhật ký nộp trên máy này?")) clearSubmissionLog();
                }}
              >
                Xóa
              </button>
            )}
          </header>
          {entries.length === 0 ? (
            <p className="submission-log__empty">Chưa nộp lần nào.</p>
          ) : (
            <ol>
              {entries.map((entry) => (
                <li key={`${entry.at}-${entry.videoId}`} data-tone={entryTone(entry)}>
                  <span className="submission-log__time">{formatClock(entry.at)}</span>
                  <span className="submission-log__mode">{entry.mode}</span>
                  <span className="submission-log__answer" title={entry.answer}>
                    <strong>{entry.videoId}</strong> {entry.answer}
                  </span>
                  <span className="submission-log__verdict">{entry.verdict}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}
    </div>
  );
}
