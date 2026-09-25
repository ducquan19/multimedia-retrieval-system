import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";

const publicConfig = {
  min_top_k: 1,
  max_top_k: 500,
  default_top_k: 100,
  max_trake_events: 4,
  max_query_length: 4_000,
  max_answer_length: 4_000,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setupApi(searchBody: Record<string, unknown> = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init: RequestInit = {}) => {
    void _init;
    const url = String(input);
    if (url.endsWith("/api/config")) return Promise.resolve(jsonResponse(publicConfig));
    if (url.endsWith("/api/objects/labels")) {
      return Promise.resolve(
        jsonResponse({ available: true, labels: ["Bicycle", "Helmet", "Person"] }),
      );
    }
    if (url.endsWith("/api/search")) {
      return Promise.resolve(
        jsonResponse({
          query_type: "KIS",
          original_query: "q",
          enhanced_query: null,
          model_choices: ["siglip"],
          applied_weights: null,
          warnings: [],
          results: [],
          ...searchBody,
        }),
      );
    }
    return Promise.resolve(jsonResponse({ detail: "Not found" }, 404));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

function searchPayload(fetchMock: ReturnType<typeof setupApi>): Record<string, unknown> {
  const call = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/api/search"));
  if (!call) throw new Error("Expected a search API call");
  return JSON.parse(String(call[1]?.body)) as Record<string, unknown>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("Object search source", () => {
  it("sends the object query with minimum counts when the Object source is enabled", async () => {
    const fetchMock = setupApi();
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "cyclists racing");
    await user.click(screen.getByLabelText("Object"));

    const objectInput = screen.getByRole("combobox", { name: "Object label" });
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/objects/labels")))
        .toBe(true),
    );
    await user.type(objectInput, "bicycle{Enter}");
    await user.type(objectInput, "Helmet");
    await user.click(screen.getByRole("button", { name: "Add" }));
    await user.selectOptions(screen.getByLabelText("Min count Bicycle"), "3");

    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(searchPayload(fetchMock)).toMatchObject({
        search_sources: { image: true, asr: false, object: true },
        object_query: [
          { label: "Bicycle", min_count: 3 },
          { label: "Helmet", min_count: 1 },
        ],
      }),
    );
  });

  it("rejects unknown labels and requires an object before searching", async () => {
    const fetchMock = setupApi();
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "a unicorn");
    await user.click(screen.getByLabelText("Object"));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/objects/labels")))
        .toBe(true),
    );
    await user.type(screen.getByRole("combobox", { name: "Object label" }), "Unicorn{Enter}");

    expect(await screen.findByText('Không có object "Unicorn" trong index.')).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(
      await screen.findByText(
        "Thêm ít nhất một object hoặc bật Enhance query để tự chọn object.",
      ),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/search"))).toBe(
      false,
    );
  });

  it("omits the object query when the Object source is off", async () => {
    const fetchMock = setupApi();
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "a street");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(searchPayload(fetchMock)).not.toHaveProperty("object_query"));
  });

  it("lets Gemini pick objects and pins an auto object into the object query", async () => {
    const fetchMock = setupApi({
      enhanced_query: "- two cyclists | Objects: Bicycle ≥2",
      applied_weights: { w_vis: 0.7, w_asr: 0, w_obj: 0.9 },
      auto_object_query: [{ label: "Bicycle", min_count: 2 }],
    });
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "hai người đạp xe");
    await user.click(screen.getByLabelText("Enhance query"));
    await user.click(screen.getByLabelText("Object"));
    expect(screen.getByText("Enhance query sẽ tự thêm object từ câu truy vấn.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() =>
      expect(searchPayload(fetchMock)).toMatchObject({
        enhance_query: true,
        search_sources: { object: true },
      }),
    );
    expect(searchPayload(fetchMock)).not.toHaveProperty("object_query");
    expect(await screen.findByText("OBJ: 0.90")).toBeInTheDocument();
    expect(screen.getByText("1 auto objects")).toBeInTheDocument();

    // The insight starts collapsed; expanding it reveals the pinnable object chips.
    await user.click(screen.getByRole("button", { name: "Mở rộng search insight" }));
    await user.click(screen.getByRole("button", { name: "Pin Bicycle" }));

    expect(screen.getByLabelText("Min count Bicycle")).toHaveValue("2");
    expect(screen.getByRole("button", { name: "Pin Bicycle" })).toBeDisabled();
  });
});
