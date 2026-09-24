import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import {
  type DresEvaluation,
  type DresSession,
  type SubmitBody,
  buildKISPayload,
  buildQAPayload,
  buildTRAKEPayload,
  dresEvaluationList,
  dresLogin,
  dresLogout,
  dresSubmit,
} from "../../api/dres";

import "./DresPanel.css";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SubmitType = "KIS" | "QA" | "TRAKE";

interface LogEntry {
  id: number;
  type: SubmitType;
  ok: boolean;
  summary: string;
  timestamp: Date;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const DRES_STORAGE_KEY = "dres-panel-state";

function loadPersistedState(): {
  serverUrl: string;
  username: string;
} {
  try {
    const raw = window.localStorage.getItem(DRES_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as { serverUrl?: string; username?: string };
      return {
        serverUrl: parsed.serverUrl ?? "https://eventretrieval.one",
        username: parsed.username ?? "",
      };
    }
  } catch {
    // ignore
  }
  return { serverUrl: "https://eventretrieval.one", username: "" };
}

export function DresPanel() {
  const persisted = loadPersistedState();

  // ---- Connection state ----
  const [serverUrl, setServerUrl] = useState(persisted.serverUrl);
  const [username, setUsername] = useState(persisted.username);
  const [password, setPassword] = useState("");
  const [session, setSession] = useState<DresSession | null>(null);
  const [evaluations, setEvaluations] = useState<DresEvaluation[]>([]);
  const [selectedEvalId, setSelectedEvalId] = useState("");

  // ---- UI state ----
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [activeTab, setActiveTab] = useState<SubmitType>("KIS");
  const [log, setLog] = useState<LogEntry[]>([]);
  const logIdRef = useRef(0);

  // ---- KIS fields ----
  const [kisVideoId, setKisVideoId] = useState("");
  const [kisStart, setKisStart] = useState("");
  const [kisEnd, setKisEnd] = useState("");

  // ---- QA fields ----
  const [qaAnswer, setQaAnswer] = useState("");
  const [qaVideoId, setQaVideoId] = useState("");
  const [qaTime, setQaTime] = useState("");

  // ---- TRAKE fields ----
  const [trakeVideoId, setTrakeVideoId] = useState("");
  const [trakeFrames, setTrakeFrames] = useState("");

  // ---- Persist server + user ----
  useEffect(() => {
    try {
      window.localStorage.setItem(
        DRES_STORAGE_KEY,
        JSON.stringify({ serverUrl, username }),
      );
    } catch {
      // ignore
    }
  }, [serverUrl, username]);

  // ---- Helpers ----
  const showFeedback = useCallback((ok: boolean, msg: string) => {
    setFeedback({ ok, msg });
    // auto-clear after 6 seconds
    setTimeout(() => setFeedback(null), 6000);
  }, []);

  const pushLog = useCallback((type: SubmitType, ok: boolean, summary: string) => {
    logIdRef.current += 1;
    setLog((prev) => [
      { id: logIdRef.current, type, ok, summary, timestamp: new Date() },
      ...prev.slice(0, 49), // keep last 50
    ]);
  }, []);

  const isConnected = session !== null;
  const canSubmit = isConnected && selectedEvalId !== "";

  // ---- Handlers ----
  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      const sess = await dresLogin(serverUrl, username, password);
      setSession(sess);
      showFeedback(true, `Đăng nhập thành công — sessionId: ${sess.sessionId.slice(0, 12)}…`);
      // Immediately fetch evaluations
      try {
        const evals = await dresEvaluationList(serverUrl, sess.sessionId);
        setEvaluations(evals);
        const active = evals.find((ev) => ev.status === "ACTIVE");
        if (active) setSelectedEvalId(active.id);
      } catch {
        // evaluation list failure is non-fatal at login time
      }
    } catch (err) {
      showFeedback(false, err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  const handleFetchEvals = async () => {
    if (!session || busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      const evals = await dresEvaluationList(serverUrl, session.sessionId);
      setEvaluations(evals);
      const active = evals.find((ev) => ev.status === "ACTIVE");
      if (active) setSelectedEvalId(active.id);
      showFeedback(true, `Nhận ${evals.length} evaluation(s)`);
    } catch (err) {
      showFeedback(false, err instanceof Error ? err.message : "Fetch failed");
    } finally {
      setBusy(false);
    }
  };

  const handleLogout = async () => {
    if (!session) return;
    setBusy(true);
    try {
      await dresLogout(serverUrl, session.sessionId);
    } catch {
      // ignore logout failures
    }
    setSession(null);
    setEvaluations([]);
    setSelectedEvalId("");
    showFeedback(true, "Đã đăng xuất.");
    setBusy(false);
  };

  const doSubmit = async (type: SubmitType, body: SubmitBody, summary: string) => {
    if (!session || !selectedEvalId || busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      await dresSubmit(serverUrl, session.sessionId, selectedEvalId, body);
      showFeedback(true, `Nộp thành công: ${summary}`);
      pushLog(type, true, summary);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Submission failed";
      showFeedback(false, msg);
      pushLog(type, false, `${summary} — ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const submitKIS = (e: FormEvent) => {
    e.preventDefault();
    const vid = kisVideoId.trim();
    const start = Number(kisStart);
    const end = Number(kisEnd);
    if (!vid) return showFeedback(false, "Video ID không được trống.");
    if (Number.isNaN(start) || Number.isNaN(end)) return showFeedback(false, "Start/End phải là số.");
    doSubmit("KIS", buildKISPayload(vid, start, end), `${vid} [${start}–${end} ms]`);
  };

  const submitQA = (e: FormEvent) => {
    e.preventDefault();
    const ans = qaAnswer.trim();
    const vid = qaVideoId.trim();
    const t = Number(qaTime);
    if (!ans || !vid) return showFeedback(false, "Answer và Video ID không được trống.");
    if (Number.isNaN(t)) return showFeedback(false, "Time phải là số.");
    doSubmit("QA", buildQAPayload(ans, vid, t), `QA-${ans}-${vid}-${t}`);
  };

  const submitTRAKE = (e: FormEvent) => {
    e.preventDefault();
    const vid = trakeVideoId.trim();
    const frames = trakeFrames
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .map(Number);
    if (!vid) return showFeedback(false, "Video ID không được trống.");
    if (frames.length === 0 || frames.some(Number.isNaN))
      return showFeedback(false, "Frame IDs phải là danh sách số, cách nhau bằng dấu phẩy.");
    doSubmit("TRAKE", buildTRAKEPayload(vid, frames), `TR-${vid}-${frames.join(",")}`);
  };

  // ---- Render ----
  return (
    <aside className={`dres-panel ${expanded ? "dres-panel--open" : ""}`}>
      {/* Toggle handle */}
      <button
        type="button"
        className="dres-panel__toggle"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label="Toggle DRES panel"
        title="DRES Submission"
      >
        <span className="dres-panel__toggle-icon">
          {expanded ? "✕" : "▲"}
        </span>
        <span className="dres-panel__toggle-label">DRES</span>
        {isConnected && <span className="dres-panel__online-dot" />}
      </button>

      {/* Panel content */}
      {expanded && (
        <div className="dres-panel__content">
          {/* ─── Connection status bar ─── */}
          <div className={`dres-status-bar ${isConnected ? "dres-status-bar--ok" : ""}`}>
            <span className="dres-status-dot" />
            <span>
              {isConnected
                ? `${session.username} — connected`
                : "Chưa kết nối"}
            </span>
            {isConnected && (
              <button
                type="button"
                className="dres-btn dres-btn--xs dres-btn--ghost"
                onClick={handleLogout}
                disabled={busy}
              >
                Logout
              </button>
            )}
          </div>

          {/* ─── Login form ─── */}
          {!isConnected && (
            <form className="dres-section" onSubmit={handleLogin}>
              <h3 className="dres-section__title">
                <span className="dres-step">1</span> Đăng nhập DRES
              </h3>
              <label className="dres-field">
                <span>Server URL</span>
                <input
                  type="url"
                  value={serverUrl}
                  onChange={(e) => setServerUrl(e.target.value)}
                  placeholder="https://eventretrieval.one"
                  className="dres-input"
                />
              </label>
              <label className="dres-field">
                <span>Username</span>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Tên đội"
                  className="dres-input"
                />
              </label>
              <label className="dres-field">
                <span>Password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••"
                  className="dres-input"
                />
              </label>
              <button type="submit" className="dres-btn dres-btn--primary" disabled={busy}>
                {busy ? "Đang kết nối…" : "→ Đăng nhập"}
              </button>
            </form>
          )}

          {/* ─── Evaluation picker ─── */}
          {isConnected && (
            <div className="dres-section">
              <h3 className="dres-section__title">
                <span className="dres-step">2</span> Chọn Evaluation
              </h3>
              <div className="dres-row">
                <select
                  className="dres-input dres-select"
                  value={selectedEvalId}
                  onChange={(e) => setSelectedEvalId(e.target.value)}
                >
                  <option value="">— chọn evaluation —</option>
                  {evaluations.map((ev) => (
                    <option key={ev.id} value={ev.id}>
                      {ev.name} ({ev.status})
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="dres-btn dres-btn--secondary"
                  onClick={handleFetchEvals}
                  disabled={busy}
                  title="Refresh evaluations"
                >
                  ↻
                </button>
              </div>
              {selectedEvalId && (
                <div className="dres-mono-id">
                  ID: <code>{selectedEvalId}</code>
                </div>
              )}
            </div>
          )}

          {/* ─── Submit area ─── */}
          {isConnected && (
            <div className="dres-section">
              <h3 className="dres-section__title">
                <span className="dres-step">3</span> Nộp kết quả
              </h3>

              {/* Tabs */}
              <div className="dres-tabs" role="tablist">
                {(["KIS", "QA", "TRAKE"] as SubmitType[]).map((t) => (
                  <button
                    key={t}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === t}
                    className={`dres-tab ${activeTab === t ? "dres-tab--active" : ""}`}
                    onClick={() => setActiveTab(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>

              {/* KIS form */}
              {activeTab === "KIS" && (
                <form className="dres-form" onSubmit={submitKIS}>
                  <p className="dres-hint">
                    Nộp khoảng thời gian (ms) trong video.
                  </p>
                  <label className="dres-field">
                    <span>Video ID</span>
                    <input
                      type="text"
                      className="dres-input"
                      value={kisVideoId}
                      onChange={(e) => setKisVideoId(e.target.value)}
                      placeholder="L01_V001"
                    />
                  </label>
                  <div className="dres-row">
                    <label className="dres-field dres-field--half">
                      <span>Start (ms)</span>
                      <input
                        type="number"
                        className="dres-input"
                        value={kisStart}
                        onChange={(e) => setKisStart(e.target.value)}
                        placeholder="0"
                        min={0}
                      />
                    </label>
                    <label className="dres-field dres-field--half">
                      <span>End (ms)</span>
                      <input
                        type="number"
                        className="dres-input"
                        value={kisEnd}
                        onChange={(e) => setKisEnd(e.target.value)}
                        placeholder="5000"
                        min={0}
                      />
                    </label>
                  </div>
                  <button
                    type="submit"
                    className="dres-btn dres-btn--primary"
                    disabled={!canSubmit || busy}
                  >
                    {busy ? "Đang nộp…" : "▲ Submit KIS"}
                  </button>
                </form>
              )}

              {/* QA form */}
              {activeTab === "QA" && (
                <form className="dres-form" onSubmit={submitQA}>
                  <p className="dres-hint">
                    Format: <code>QA-ANSWER-VIDEO_ID-TIME(ms)</code>
                  </p>
                  <label className="dres-field">
                    <span>Answer</span>
                    <input
                      type="text"
                      className="dres-input"
                      value={qaAnswer}
                      onChange={(e) => setQaAnswer(e.target.value)}
                      placeholder="Câu trả lời"
                    />
                  </label>
                  <div className="dres-row">
                    <label className="dres-field dres-field--half">
                      <span>Video ID</span>
                      <input
                        type="text"
                        className="dres-input"
                        value={qaVideoId}
                        onChange={(e) => setQaVideoId(e.target.value)}
                        placeholder="L01_V001"
                      />
                    </label>
                    <label className="dres-field dres-field--half">
                      <span>Time (ms)</span>
                      <input
                        type="number"
                        className="dres-input"
                        value={qaTime}
                        onChange={(e) => setQaTime(e.target.value)}
                        placeholder="0"
                        min={0}
                      />
                    </label>
                  </div>
                  <button
                    type="submit"
                    className="dres-btn dres-btn--primary"
                    disabled={!canSubmit || busy}
                  >
                    {busy ? "Đang nộp…" : "▲ Submit QA"}
                  </button>
                </form>
              )}

              {/* TRAKE form */}
              {activeTab === "TRAKE" && (
                <form className="dres-form" onSubmit={submitTRAKE}>
                  <p className="dres-hint">
                    Format: <code>TR-VIDEO_ID-FRAME1,FRAME2,…</code>
                  </p>
                  <label className="dres-field">
                    <span>Video ID</span>
                    <input
                      type="text"
                      className="dres-input"
                      value={trakeVideoId}
                      onChange={(e) => setTrakeVideoId(e.target.value)}
                      placeholder="L01_V001"
                    />
                  </label>
                  <label className="dres-field">
                    <span>Frame IDs (phân cách bằng dấu phẩy)</span>
                    <input
                      type="text"
                      className="dres-input"
                      value={trakeFrames}
                      onChange={(e) => setTrakeFrames(e.target.value)}
                      placeholder="100,200,300,400"
                    />
                  </label>
                  <button
                    type="submit"
                    className="dres-btn dres-btn--primary"
                    disabled={!canSubmit || busy}
                  >
                    {busy ? "Đang nộp…" : "▲ Submit TRAKE"}
                  </button>
                </form>
              )}
            </div>
          )}

          {/* ─── Feedback toast ─── */}
          {feedback && (
            <div
              className={`dres-toast ${feedback.ok ? "dres-toast--ok" : "dres-toast--err"}`}
              role="status"
            >
              {feedback.msg}
            </div>
          )}

          {/* ─── Submission log ─── */}
          {log.length > 0 && (
            <div className="dres-section dres-log">
              <div className="dres-section__header">
                <h3 className="dres-section__title">Lịch sử nộp</h3>
                <button
                  type="button"
                  className="dres-btn dres-btn--xs dres-btn--ghost"
                  onClick={() => setLog([])}
                >
                  Xoá
                </button>
              </div>
              <ul className="dres-log__list">
                {log.map((entry) => (
                  <li
                    key={entry.id}
                    className={`dres-log__item ${entry.ok ? "dres-log__item--ok" : "dres-log__item--err"}`}
                  >
                    <span className="dres-log__badge">{entry.type}</span>
                    <span className="dres-log__text">{entry.summary}</span>
                    <span className="dres-log__time">
                      {entry.timestamp.toLocaleTimeString()}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
