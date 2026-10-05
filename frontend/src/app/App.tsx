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
            Đang kết nối backend…
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
