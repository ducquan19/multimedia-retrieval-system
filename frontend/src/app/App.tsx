import { useQuery } from "@tanstack/react-query";

import { ApiError, getPublicConfig } from "../api/client";
import { SearchWorkspace } from "../features/search/SearchWorkspace";

import "./app.css";

// scripts/dev.py starts Vite in about a second, while the backend needs ~30 s to load its
// models and indexes. Until then the proxy fails, so keep asking for about two minutes.
const STARTUP_RETRIES = 60;
const STARTUP_RETRY_MAX_DELAY_MS = 2_000;

function isBackendStarting(error: unknown): boolean {
  // No status: the request never reached the backend. 5xx: the dev proxy could not connect.
  return error instanceof ApiError && (error.status === undefined || error.status >= 500);
}

export function App() {
  const configQuery = useQuery({
    queryKey: ["public-config"],
    queryFn: ({ signal }) => getPublicConfig(signal),
    retry: (failureCount, error) => failureCount < STARTUP_RETRIES && isBackendStarting(error),
    retryDelay: (attempt) => Math.min(500 * 2 ** attempt, STARTUP_RETRY_MAX_DELAY_MS),
  });

  return (
    <div className="app-shell">
      <main className="app-main">
        {configQuery.isPending && (
          <section className="bootstrap-state" aria-live="polite">
            {configQuery.failureCount > 0
              ? "Đang chờ backend khởi động (nạp model và index)…"
              : "Đang kết nối backend…"}
          </section>
        )}
        {configQuery.isError && (
          <section className="bootstrap-state bootstrap-state--error" role="alert">
            Không kết nối được backend. Kiểm tra backend đang chạy ở cổng 8000 rồi tải lại trang.
          </section>
        )}
        {configQuery.data && <SearchWorkspace config={configQuery.data} />}
      </main>
    </div>
  );
}
