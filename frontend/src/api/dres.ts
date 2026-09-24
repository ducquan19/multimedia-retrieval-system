// ---------------------------------------------------------------------------
// DRES (Distributed Retrieval Evaluation Server) API client
// ---------------------------------------------------------------------------

/** Session returned after a successful login. */
export interface DresSession {
  id: string;
  username: string;
  role: string;
  sessionId: string;
}

/** A single evaluation entry returned by the server. */
export interface DresEvaluation {
  id: string;
  name: string;
  type: string;
  status: string;
}

/** Generic wrapper for DRES API errors. */
export class DresApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "DresApiError";
  }
}

// ---- KIS answer body ----
export interface KISAnswer {
  mediaItemName: string;
  start: string;
  end: string;
}

// ---- QA answer body ----
export interface QAAnswer {
  text: string; // "QA-<ANSWER>-<VIDEO_ID>-<TIME(ms)>"
}

// ---- TRAKE answer body ----
export interface TRAKEAnswer {
  text: string; // "TR-<VIDEO_ID>-<FRAME_ID1>,<FRAME_ID2>,..."
}

export type AnswerItem = KISAnswer | QAAnswer | TRAKEAnswer;

export interface SubmitBody {
  answerSets: { answers: AnswerItem[] }[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function dresRequest<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...init.headers,
      },
    });
  } catch {
    throw new DresApiError("Cannot connect to DRES server.");
  }

  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { description?: string; message?: string };
      detail = body.description ?? body.message ?? "";
    } catch {
      // fall through
    }
    throw new DresApiError(
      detail || `DRES request failed (HTTP ${response.status})`,
      response.status,
    );
  }

  return (await response.json()) as T;
}

function stripTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Step 1 – Log in and obtain a sessionId. */
export function dresLogin(
  serverUrl: string,
  username: string,
  password: string,
): Promise<DresSession> {
  const base = stripTrailingSlash(serverUrl);
  return dresRequest<DresSession>(`${base}/api/v2/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

/** Step 2 – Fetch the list of evaluations. */
export function dresEvaluationList(
  serverUrl: string,
  sessionId: string,
): Promise<DresEvaluation[]> {
  const base = stripTrailingSlash(serverUrl);
  const url = new URL(`${base}/api/v2/client/evaluation/list`);
  url.searchParams.set("session", sessionId);
  return dresRequest<DresEvaluation[]>(url.toString());
}

/** Step 3 – Submit an answer. */
export function dresSubmit(
  serverUrl: string,
  sessionId: string,
  evaluationId: string,
  body: SubmitBody,
): Promise<unknown> {
  const base = stripTrailingSlash(serverUrl);
  const url = new URL(`${base}/api/v2/submit/${encodeURIComponent(evaluationId)}`);
  url.searchParams.set("session", sessionId);
  return dresRequest<unknown>(url.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Logout. */
export function dresLogout(
  serverUrl: string,
  sessionId: string,
): Promise<unknown> {
  const base = stripTrailingSlash(serverUrl);
  const url = new URL(`${base}/api/v2/logout`);
  url.searchParams.set("session", sessionId);
  return dresRequest<unknown>(url.toString());
}

// ---------------------------------------------------------------------------
// Payload builders  –  convenience helpers for the three answer types.
// ---------------------------------------------------------------------------

export function buildKISPayload(
  videoId: string,
  startMs: number,
  endMs: number,
): SubmitBody {
  return {
    answerSets: [
      {
        answers: [
          {
            mediaItemName: videoId,
            start: String(startMs),
            end: String(endMs),
          },
        ],
      },
    ],
  };
}

export function buildQAPayload(
  answer: string,
  videoId: string,
  timeMs: number,
): SubmitBody {
  return {
    answerSets: [
      {
        answers: [{ text: `QA-${answer}-${videoId}-${timeMs}` }],
      },
    ],
  };
}

export function buildTRAKEPayload(
  videoId: string,
  frameIds: number[],
): SubmitBody {
  return {
    answerSets: [
      {
        answers: [{ text: `TR-${videoId}-${frameIds.join(",")}` }],
      },
    ],
  };
}
