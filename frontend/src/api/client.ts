import type {
  PublicConfig,
  SearchRequest,
  SearchResponse,
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
