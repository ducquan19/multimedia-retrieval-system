import { useQuery } from "@tanstack/react-query";

import { getPublicConfig } from "../api/client";
import { getHealth } from "../api/health";
import { SearchWorkspace } from "../features/search/SearchWorkspace";

import "./app.css";

function HealthStatus() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
    retry: false,
  });

  if (healthQuery.isPending) {
    return <p className="status status--pending">Đang kết nối backend…</p>;
  }

  if (healthQuery.isError) {
    return (
      <p className="status status--error" role="alert">
        Backend chưa sẵn sàng. Hãy kiểm tra API đang chạy.
      </p>
    );
  }

  return (
    <p className="status status--ready">
      <span className="status__dot" aria-hidden="true" />
      Backend connected: {healthQuery.data.status}
    </p>
  );
}

export function App() {
  const configQuery = useQuery({
    queryKey: ["public-config"],
    queryFn: ({ signal }) => getPublicConfig(signal),
    retry: false,
  });

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">HCMC AI Challenge 2026</p>
          <h1>AIC Retrieval Inspector</h1>
        </div>
        <div className="header-status">
          <HealthStatus />
          <span className="badge">Mock retrieval</span>
        </div>
      </header>

      <main className="app-main">
        {configQuery.isPending && (
          <section className="bootstrap-state" aria-live="polite">
            Đang tải cấu hình workspace…
          </section>
        )}
        {configQuery.isError && (
          <section className="bootstrap-state bootstrap-state--error" role="alert">
            Không tải được cấu hình tìm kiếm. Hãy kiểm tra backend và thử tải lại trang.
          </section>
        )}
        {configQuery.data && <SearchWorkspace config={configQuery.data} />}
      </main>
    </div>
  );
}
