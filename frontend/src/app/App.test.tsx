import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("renders the mock app shell and reports backend health", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderApp();

    expect(screen.getByRole("heading", { name: "AIC Retrieval Inspector" })).toBeInTheDocument();
    expect(screen.getByText("Mock retrieval")).toBeInTheDocument();
    expect(await screen.findByText("Backend connected: ok")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/health",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("shows a friendly error when the backend is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Network error")));

    renderApp();

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend chưa sẵn sàng");
  });
});
