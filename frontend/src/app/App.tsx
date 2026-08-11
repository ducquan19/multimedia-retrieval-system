import { useQuery } from "@tanstack/react-query";

import { getPublicConfig } from "../api/client";
import { SearchWorkspace } from "../features/search/SearchWorkspace";

import "./app.css";

export function App() {
  const configQuery = useQuery({
    queryKey: ["public-config"],
    queryFn: ({ signal }) => getPublicConfig(signal),
    retry: false,
  });

  return (
    <div className="app-shell">
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
