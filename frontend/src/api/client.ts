import type {
  PublicConfig,
  SearchRequest,
  SearchResponse,
  SubmissionDownload,
  SubmissionRenderResponse,
  SubmissionRequest,
} from "./types";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export function resolveMediaUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function requestJson<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      ...options,
      headers: {
        Accept: "application/json",
        ...options.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("Không thể kết nối tới backend. Hãy kiểm tra API đang chạy.");
  }

  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      // The status-based fallback below is enough for a non-JSON response.
    }

    const fallback =
      response.status === 422
        ? "Dữ liệu gửi lên chưa hợp lệ."
        : response.status >= 500
          ? "Backend gặp lỗi khi xử lý tìm kiếm."
          : "Yêu cầu không thể hoàn tất.";
    throw new ApiError(detail || fallback, response.status);
  }

  return (await response.json()) as T;
}

async function submissionResponse(
  path: string,
  payload: SubmissionRequest,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      method: "POST",
      headers: {
        Accept: path.endsWith("/download") ? "text/csv" : "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError("Không thể kết nối tới backend. Hãy kiểm tra API đang chạy.");
  }

  if (!response.ok) {
    let detail = "Không thể tạo submission.";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Keep the submission-specific fallback for non-JSON errors.
    }
    throw new ApiError(detail, response.status);
  }
  return response;
}

export function renderSubmission(
  payload: SubmissionRequest,
): Promise<SubmissionRenderResponse> {
  return submissionResponse("/api/submissions/render", payload).then(
    (response) => response.json() as Promise<SubmissionRenderResponse>,
  );
}

export async function downloadSubmission(
  payload: SubmissionRequest,
): Promise<SubmissionDownload> {
  const response = await submissionResponse("/api/submissions/download", payload);
  return {
    blob: await response.blob(),
    filename: attachmentFilename(response.headers.get("Content-Disposition")),
  };
}

export function attachmentFilename(contentDisposition: string | null): string {
  if (!contentDisposition) return "submission.csv";
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(contentDisposition);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      // Fall through to the ASCII attachment filename.
    }
  }
  const asciiMatch = /filename="?([^";]+)"?/i.exec(contentDisposition);
  return asciiMatch?.[1] ?? "submission.csv";
}

export function getPublicConfig(signal?: AbortSignal): Promise<PublicConfig> {
  return requestJson<PublicConfig>("/api/config", { signal });
}

export function search(payload: SearchRequest, signal?: AbortSignal): Promise<SearchResponse> {
  return requestJson<SearchResponse>("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
}

export function friendlySearchError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 422) {
      return `Không thể tìm kiếm: ${error.message}`;
    }
    return error.message;
  }
  return "Không thể hoàn tất tìm kiếm. Vui lòng thử lại.";
}

export function friendlySubmissionError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Không thể tạo submission. Vui lòng thử lại.";
}
