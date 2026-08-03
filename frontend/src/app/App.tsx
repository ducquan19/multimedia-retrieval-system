import { useQuery } from "@tanstack/react-query";

import { getHealth } from "../api/health";

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
  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">HCMC AI Challenge 2026</p>
          <h1>AIC Retrieval Inspector</h1>
        </div>
        <span className="badge">Mock retrieval</span>
      </header>

      <main className="app-main">
        <section className="welcome-panel" aria-labelledby="welcome-heading">
          <div>
            <p className="eyebrow">Developer baseline</p>
            <h2 id="welcome-heading">Workspace đã sẵn sàng</h2>
            <p className="welcome-copy">
              Search forms và result inspector sẽ được bổ sung ở các milestone tiếp theo.
              Scaffold hiện chỉ kiểm tra kết nối local tới FastAPI.
            </p>
          </div>
          <HealthStatus />
        </section>
      </main>
    </div>
  );
}
