import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  ApiError,
  getDresEvaluations,
  getVideoSource,
  submitToDres,
} from "../../api/client";
import type { DresSubmitBody, DresSubmitResponse } from "../../api/types";
import { appendSubmissionLog, formatClock, useSubmissionLog } from "./submissionLog";

const EVALUATION_STORAGE_KEY = "aic-dres-evaluation";

export type SubmitMode = "KIS" | "VQA" | "TRAKE";

export type SubmitTarget =
  | {
      kind: "single";
      videoId: string;
      frameId: number;
      /** Original presentation time (ms) of the keyframe, for VFR videos. */
      timeMs?: number | null;
      defaultMode: "KIS" | "VQA";
      answer: string;
    }
  | { kind: "trake"; videoId: string; frameIds: number[]; eventIndex: number };

interface DresSubmitPanelProps {
  target: SubmitTarget;
  /** Frame currently shown by the video player, when it is open. */
  currentFrame: number | null;
  /** Original time (ms) currently shown by the player, for VFR videos (overrides the frame). */
  currentTimeMs?: number | null;
  onCancel: () => void;
}

export function frameToMs(frame: number, fps: number): number {
  return Math.round((frame / fps) * 1000);
}

export function buildSubmitBody(
  mode: SubmitMode,
  fields: { videoId: string; start: number; end: number; answer: string; frameIds: string },
): DresSubmitBody {
  if (mode === "KIS") {
    return {
      answerSets: [
        {
          answers: [
            // The final-round guide sends the times as strings: "start": "<TIME(ms)>".
            { mediaItemName: fields.videoId, start: String(fields.start), end: String(fields.end) },
          ],
        },
      ],
    };
  }
  if (mode === "VQA") {
    return {
      answerSets: [
        { answers: [{ text: `QA-${fields.answer.trim()}-${fields.videoId}-${fields.start}` }] },
      ],
    };
  }
  return {
    answerSets: [{ answers: [{ text: `TR-${fields.videoId}-${normalizeFrameIds(fields.frameIds)}` }] }],
  };
}

function normalizeFrameIds(value: string): string {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .join(",");
}

function describeAnswer(body: DresSubmitBody): string {
  const answer = body.answerSets[0]?.answers[0];
  if (!answer) return "";
  return "text" in answer ? answer.text : `${answer.start}–${answer.end} ms`;
}

/** Explain DRES filter rejections that mean "wrong answer type for the current task". */
export function rejectionHint(message: string | null | undefined, mode: SubmitMode): string | null {
  // DRES's temporal filter on KIS tasks rejects text (QA / TRAKE) answers with this message.
  if (!message || mode === "KIS" || !/non-temporal/i.test(message)) return null;
  const sent = mode === "VQA" ? "QA" : "TRAKE";
  return `Task đang chạy là KIS: DRES chỉ nhận mediaItemName + start/end, không nhận ${sent}. Chọn KIS rồi nộp lại.`;
}

function readStoredEvaluation(): string | null {
  try {
    return window.localStorage.getItem(EVALUATION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeEvaluation(id: string) {
  try {
    window.localStorage.setItem(EVALUATION_STORAGE_KEY, id);
  } catch {
    // The selection still applies for this panel when storage is unavailable.
  }
}

function toMs(value: string): number | null {
  const parsed = Number(value);
  return value.trim() !== "" && Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

export function DresSubmitPanel({
  target,
  currentFrame,
  currentTimeMs = null,
  onCancel,
}: DresSubmitPanelProps) {
  const [mode, setMode] = useState<SubmitMode>(
    target.kind === "trake" ? "TRAKE" : target.defaultMode,
  );
  const [evaluationId, setEvaluationId] = useState<string>(readStoredEvaluation() ?? "");
  const [start, setStart] = useState<string | null>(null);
  const [end, setEnd] = useState<string | null>(null);
  const [answer, setAnswer] = useState(target.kind === "single" ? target.answer : "");
  const [frameIds, setFrameIds] = useState(
    target.kind === "trake" ? target.frameIds.join(",") : "",
  );

  const evaluationsQuery = useQuery({
    queryKey: ["dres-evaluations"],
    queryFn: ({ signal }) => getDresEvaluations(signal),
    retry: false,
    staleTime: 60_000,
  });
  const sourceQuery = useQuery({
    queryKey: ["video-source", target.videoId],
    queryFn: ({ signal }) => getVideoSource(target.videoId, signal),
    retry: false,
    enabled: target.kind === "single",
    staleTime: Infinity,
  });
  const submitMutation = useMutation<DresSubmitResponse, unknown, boolean>({
    mutationFn: (allowDuplicate) =>
      submitToDres({ evaluation_id: evaluationId, ...body, allow_duplicate: allowDuplicate }),
    onSuccess: (response) =>
      logSubmission(
        response.submission ?? (response.accepted ? "Đã nộp" : "Nộp thất bại"),
        response.accepted,
      ),
    onError: (error) => {
      // A 409 is the backend's duplicate guard: nothing reached DRES.
      if (error instanceof ApiError && error.status === 409) return;
      logSubmission(error instanceof ApiError ? error.message : "Lỗi kết nối", false);
    },
  });

  // The modal can move to another keyframe; start over from the new target.
  const targetKey =
    target.kind === "trake"
      ? `${target.videoId}|${target.frameIds.join(",")}`
      : `${target.videoId}|${target.frameId}|${target.timeMs ?? ""}`;
  const { reset: resetSubmission } = submitMutation;
  useEffect(() => {
    setStart(null);
    setEnd(null);
    if (target.kind === "trake") setFrameIds(target.frameIds.join(","));
    resetSubmission();
  }, [targetKey, resetSubmission]);

  const submissionLog = useSubmissionLog();
  const previousForVideo = submissionLog.filter(
    (entry) => entry.videoId === target.videoId && entry.evaluationId === evaluationId,
  );
  const lastForVideo = previousForVideo[0];

  const evaluations = evaluationsQuery.data ?? [];
  useEffect(() => {
    if (evaluations.length === 0 || evaluations.some((item) => item.id === evaluationId)) return;
    const active = evaluations.find((item) => item.status === "ACTIVE") ?? evaluations[0];
    if (active) setEvaluationId(active.id);
  }, [evaluations, evaluationId]);

  const fps = sourceQuery.data?.fps;
  const targetTimeMs = target.kind === "single" ? (target.timeMs ?? null) : null;
  const keyframeMs =
    targetTimeMs !== null
      ? targetTimeMs
      : target.kind === "single" && fps !== undefined
        ? frameToMs(target.frameId, fps)
        : null;
  const startValue = start ?? (keyframeMs === null ? "" : String(keyframeMs));
  const endValue = end ?? (keyframeMs === null ? "" : String(keyframeMs));
  const startMs = toMs(startValue);
  const endMs = toMs(endValue);

  const body = buildSubmitBody(mode, {
    videoId: target.videoId,
    start: startMs ?? 0,
    end: endMs ?? 0,
    answer,
    frameIds,
  });

  const errors: string[] = [];
  if (!evaluationId) errors.push("Chọn evaluation.");
  if (mode !== "TRAKE" && startMs === null) errors.push("Start phải là số nguyên ms ≥ 0.");
  if (mode === "KIS" && endMs === null) errors.push("End phải là số nguyên ms ≥ 0.");
  if (mode === "KIS" && startMs !== null && endMs !== null && startMs > endMs) {
    errors.push("Start không được lớn hơn End.");
  }
  if (mode === "VQA" && !answer.trim()) errors.push("Nhập câu trả lời VQA.");
  if (mode === "TRAKE" && !/^\d+(,\d+)*$/.test(normalizeFrameIds(frameIds))) {
    errors.push("Frame IDs phải là danh sách số, cách nhau bởi dấu phẩy.");
  }

  const applyCurrentFrame = () => {
    if (target.kind === "single" && currentTimeMs !== null) {
      setStart(String(currentTimeMs));
      setEnd(String(currentTimeMs));
      return;
    }
    if (currentFrame === null) return;
    if (target.kind === "trake") {
      const frames = normalizeFrameIds(frameIds).split(",");
      frames[target.eventIndex - 1] = String(currentFrame);
      setFrameIds(frames.join(","));
    } else if (fps !== undefined) {
      const ms = String(frameToMs(currentFrame, fps));
      setStart(ms);
      setEnd(ms);
    }
  };

  function logSubmission(verdict: string, ok: boolean) {
    appendSubmissionLog({
      at: Date.now(),
      evaluationId,
      mode,
      videoId: target.videoId,
      answer: describeAnswer(body),
      verdict,
      ok,
    });
  }

  const duplicateError =
    submitMutation.error instanceof ApiError && submitMutation.error.status === 409;
  const locked = submitMutation.isPending || submitMutation.data !== undefined;

  return (
    <section className="dres-panel" aria-label="Submit to DRES">
      <header className="dres-panel__header">
        <h3>Submit to DRES</h3>
        {target.kind === "single" && (
          <div className="dres-panel__modes" role="radiogroup" aria-label="Submission type">
            {(["KIS", "VQA"] as const).map((option) => (
              <label key={option}>
                <input
                  type="radio"
                  name="dres-mode"
                  value={option}
                  checked={mode === option}
                  disabled={locked}
                  onChange={() => setMode(option)}
                />
                {option}
              </label>
            ))}
          </div>
        )}
      </header>

      <label className="dres-panel__field">
        <span>Evaluation</span>
        {evaluationsQuery.isError ? (
          <small className="dres-panel__error" role="alert">
            {evaluationsQuery.error instanceof ApiError
              ? evaluationsQuery.error.message
              : "Không tải được danh sách evaluation."}
          </small>
        ) : (
          <select
            aria-label="Evaluation"
            value={evaluationId}
            disabled={locked || evaluationsQuery.isPending}
            onChange={(event) => {
              setEvaluationId(event.target.value);
              storeEvaluation(event.target.value);
            }}
          >
            {evaluationsQuery.isPending && <option value="">Đang tải…</option>}
            {evaluations.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} {item.status ? `(${item.status})` : ""}
              </option>
            ))}
          </select>
        )}
      </label>

      {mode === "TRAKE" ? (
        <label className="dres-panel__field">
          <span>Frame IDs</span>
          <input
            type="text"
            aria-label="Frame IDs"
            value={frameIds}
            disabled={locked}
            onChange={(event) => setFrameIds(event.target.value)}
          />
        </label>
      ) : (
        <>
          {mode === "VQA" && (
            <label className="dres-panel__field">
              <span>Answer</span>
              <input
                type="text"
                aria-label="VQA answer"
                value={answer}
                disabled={locked}
                onChange={(event) => setAnswer(event.target.value)}
              />
            </label>
          )}
          <div className="dres-panel__times">
            <label className="dres-panel__field">
              <span>{mode === "KIS" ? "Start (ms)" : "Time (ms)"}</span>
              <input
                type="number"
                min={0}
                step={1}
                aria-label={mode === "KIS" ? "Start (ms)" : "Time (ms)"}
                value={startValue}
                disabled={locked}
                onChange={(event) => setStart(event.target.value)}
              />
            </label>
            {mode === "KIS" && (
              <label className="dres-panel__field">
                <span>End (ms)</span>
                <input
                  type="number"
                  min={0}
                  step={1}
                  aria-label="End (ms)"
                  value={endValue}
                  disabled={locked}
                  onChange={(event) => setEnd(event.target.value)}
                />
              </label>
            )}
          </div>
          {sourceQuery.isError && targetTimeMs === null && (
            <small className="dres-panel__error">
              Không lấy được FPS của video; hãy nhập thời gian (ms) thủ công.
            </small>
          )}
          {targetTimeMs !== null ? (
            <small className="dres-panel__hint">
              Keyframe tại {targetTimeMs} ms (thời gian gốc của video)
            </small>
          ) : (
            fps !== undefined && (
              <small className="dres-panel__hint">
                Frame {target.kind === "single" ? target.frameId : ""} @ {fps} fps = {keyframeMs} ms
              </small>
            )
          )}
        </>
      )}

      {target.kind === "single" && currentTimeMs !== null && !locked ? (
        <button type="button" className="dres-panel__secondary" onClick={applyCurrentFrame}>
          {`Dùng thời điểm đang xem (${currentTimeMs} ms)`}
        </button>
      ) : (
        currentFrame !== null &&
        !locked && (
          <button type="button" className="dres-panel__secondary" onClick={applyCurrentFrame}>
            {target.kind === "trake"
              ? `Dùng frame đang xem (${currentFrame}) cho EVENT ${target.eventIndex}`
              : `Dùng frame đang xem (${currentFrame})`}
          </button>
        )
      )}

      {lastForVideo && !locked && (
        <p className="dres-panel__history" role="note">
          Đã nộp {target.videoId} {previousForVideo.length} lần trong evaluation này — lần cuối{" "}
          {formatClock(lastForVideo.at)}: <strong>{lastForVideo.verdict}</strong> (
          {lastForVideo.answer})
        </p>
      )}

      <pre className="dres-panel__preview" aria-label="Request body">
        {JSON.stringify(body, null, 2)}
      </pre>

      {errors.length > 0 && !locked && (
        <ul className="dres-panel__error">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}

      {submitMutation.data && (
        <p
          className={`dres-panel__result dres-panel__result--${
            submitMutation.data.accepted ? "ok" : "fail"
          }`}
          role="status"
        >
          <strong>
            {submitMutation.data.submission ??
              (submitMutation.data.accepted ? "Đã nộp" : "Nộp thất bại")}
          </strong>
          {submitMutation.data.description && <span>{submitMutation.data.description}</span>}
          {!submitMutation.data.accepted && rejectionHint(submitMutation.data.description, mode) && (
            <em className="dres-panel__hint-strong">
              {rejectionHint(submitMutation.data.description, mode)}
            </em>
          )}
        </p>
      )}
      {submitMutation.isError && (
        <p className="dres-panel__result dres-panel__result--fail" role="alert">
          <strong>{duplicateError ? "Đã nộp đáp án này" : "Nộp thất bại"}</strong>
          <span>
            {submitMutation.error instanceof ApiError
              ? submitMutation.error.message
              : "Không thể kết nối tới backend."}
          </span>
          {submitMutation.error instanceof ApiError &&
            rejectionHint(submitMutation.error.message, mode) && (
              <em className="dres-panel__hint-strong">
                {rejectionHint(submitMutation.error.message, mode)}
              </em>
            )}
        </p>
      )}

      <footer className="dres-panel__actions">
        <button type="button" className="dres-panel__secondary" onClick={onCancel}>
          {submitMutation.data ? "Đóng" : "Hủy"}
        </button>
        {!submitMutation.data &&
          (duplicateError ? (
            <button
              type="button"
              className="dres-panel__confirm dres-panel__confirm--danger"
              onClick={() => submitMutation.mutate(true)}
            >
              Vẫn nộp lại
            </button>
          ) : (
            <button
              type="button"
              className="dres-panel__confirm"
              disabled={errors.length > 0 || submitMutation.isPending}
              onClick={() => submitMutation.mutate(false)}
            >
              {submitMutation.isPending ? "Đang nộp…" : "Xác nhận nộp"}
            </button>
          ))}
      </footer>
    </section>
  );
}
