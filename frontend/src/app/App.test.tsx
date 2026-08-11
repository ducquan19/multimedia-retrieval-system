import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { QueryType } from "../api/types";
import { App } from "./App";

const publicConfig = {
  top_k_options: [1, 5, 20, 50, 100],
  default_top_k: 20,
  max_trake_events: 4,
  max_query_length: 4_000,
  max_answer_length: 4_000,
  retrieval_mode: "mock",
  gemini_mode: "mock",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function searchResponse(
  queryType: QueryType,
  options: { enhanced?: boolean; empty?: boolean } = {},
) {
  return {
    query_type: queryType,
    original_query: "original query",
    enhanced_query: options.enhanced ? "[Mock enhanced KIS] original query" : null,
    retrieval_mode: "mock",
    results: options.empty
      ? []
      : [
          {
            result_id: "result-001",
            rank: 1,
            video_id: "L01_V001",
            frame_id: 505,
            keyframe_url: "/media/keyframes/mock-frame.svg",
            segment_id: "segment-001",
            asr_text: "Một người đang mở laptop.",
            ocr_text: "AIC 2026",
            objects: [{ label: "laptop", score: 0.97 }],
            similarity_score: 0.9821,
            answer: "",
          },
        ],
  };
}

type SearchHandler = (init: RequestInit) => Response | Promise<Response>;

function setupApi(searchHandler: SearchHandler = () => jsonResponse(searchResponse("KIS"))) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    if (url.endsWith("/api/health")) return Promise.resolve(jsonResponse({ status: "ok" }));
    if (url.endsWith("/api/config")) return Promise.resolve(jsonResponse(publicConfig));
    if (url.endsWith("/api/search")) return Promise.resolve(searchHandler(init));
    return Promise.resolve(jsonResponse({ detail: "Not found" }, 404));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
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
});

describe("App query workspace", () => {
  it("renders the mock shell and switches between KIS, VQA and TRAKE tabs", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();

    expect(screen.getByRole("heading", { name: "AIC Retrieval Inspector" })).toBeInTheDocument();
    expect(screen.getByText("Mock retrieval")).toBeInTheDocument();
    expect(await screen.findByText("Backend connected: ok")).toBeInTheDocument();
    expect(await screen.findByLabelText(/^Query KIS/)).toBeInTheDocument();
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual([
      "1",
      "5",
      "20",
      "50",
      "100",
    ]);

    await user.click(screen.getByRole("tab", { name: /VQA/ }));
    expect(screen.getByLabelText(/^Câu hỏi VQA/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Query KIS/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /TRAKE/ }));
    expect(screen.getByLabelText(/^Main query TRAKE/)).toBeInTheDocument();
    expect(screen.getByLabelText("Event 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Event 2")).toBeInTheDocument();
  });

  it("submits the typed KIS payload with shared controls", async () => {
    const fetchMock = setupApi(() => jsonResponse(searchResponse("KIS", { empty: true })));
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "người mở laptop");
    await user.selectOptions(screen.getByLabelText("Top K"), "5");
    await user.click(screen.getByLabelText(/^Enhance query/));
    await user.click(screen.getByLabelText("ASR"));
    await user.click(screen.getByRole("button", { name: "Search KIS" }));

    await screen.findByText("Không tìm thấy candidate");
    expect(searchPayload(fetchMock)).toEqual({
      query_type: "KIS",
      query: "người mở laptop",
      top_k: 5,
      enhance_query: true,
      search_sources: { image: true, asr: true, object: false, ocr: false },
    });
  });

  it("uses Enter to search and Shift+Enter to insert a query newline", async () => {
    const fetchMock = setupApi(() => jsonResponse(searchResponse("KIS", { empty: true })));
    const user = userEvent.setup();
    renderApp();

    const query = await screen.findByLabelText(/^Query KIS/);
    await user.type(query, "dòng một");
    await user.keyboard("{Shift>}{Enter}{/Shift}dòng hai");

    expect(query).toHaveValue("dòng một\ndòng hai");
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/search"))).toBe(
      false,
    );

    await user.keyboard("{Enter}");

    await screen.findByText("Không tìm thấy candidate");
    expect(searchPayload(fetchMock)).toMatchObject({ query: "dòng một\ndòng hai" });
  });

  it("submits the typed VQA payload without an answer field", async () => {
    const fetchMock = setupApi(() => jsonResponse(searchResponse("VQA", { empty: true })));
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("tab", { name: /VQA/ }));
    await user.type(screen.getByLabelText(/^Câu hỏi VQA/), "chiếc ly màu gì?");
    await user.click(screen.getByRole("button", { name: "Search VQA" }));

    await screen.findByText("Không tìm thấy candidate");
    expect(searchPayload(fetchMock)).toEqual({
      query_type: "VQA",
      query: "chiếc ly màu gì?",
      top_k: 20,
      enhance_query: false,
      search_sources: { image: true, asr: false, object: false, ocr: false },
    });
    expect(searchPayload(fetchMock)).not.toHaveProperty("answer");
  });

  it("keeps hidden TRAKE event text and submits continuous event indices", async () => {
    const fetchMock = setupApi(() => jsonResponse(searchResponse("TRAKE", { empty: true })));
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("tab", { name: /TRAKE/ }));
    await user.type(screen.getByLabelText(/^Main query TRAKE/), "chuỗi nhảy cao");
    await user.type(screen.getByLabelText("Event 1"), "giậm nhảy");
    await user.type(screen.getByLabelText("Event 2"), "bay qua xà");

    await user.selectOptions(screen.getByLabelText("Event count"), "1");
    expect(screen.queryByLabelText("Event 2")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Event count"), "2");
    expect(screen.getByLabelText("Event 2")).toHaveValue("bay qua xà");

    await user.selectOptions(screen.getByLabelText("Event count"), "3");
    await user.type(screen.getByLabelText("Event 3"), "tiếp đất");
    await user.click(screen.getByRole("button", { name: "Search TRAKE" }));

    await screen.findByText("Không tìm thấy candidate");
    expect(searchPayload(fetchMock)).toMatchObject({
      query_type: "TRAKE",
      main_query: "chuỗi nhảy cao",
      events: [
        { event_index: 1, query: "giậm nhảy" },
        { event_index: 2, query: "bay qua xà" },
        { event_index: 3, query: "tiếp đất" },
      ],
    });
  });

  it("validates that at least one hybrid source is selected", async () => {
    const fetchMock = setupApi();
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "query hợp lệ");
    await user.click(screen.getByLabelText("Image"));
    await user.click(screen.getByRole("button", { name: "Search KIS" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Chọn ít nhất một nguồn tìm kiếm");
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/search"))).toBe(
      false,
    );
  });

  it("shows original and enhanced query with a Mock badge", async () => {
    setupApi(() => jsonResponse(searchResponse("KIS", { enhanced: true })));
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "original query");
    await user.click(screen.getByLabelText(/^Enhance query/));
    await user.click(screen.getByRole("button", { name: "Search KIS" }));

    const callout = await screen.findByLabelText("Enhanced query");
    expect(callout).toHaveTextContent("Original");
    expect(callout).toHaveTextContent("original query");
    expect(callout).toHaveTextContent("Enhanced");
    expect(callout).toHaveTextContent("[Mock enhanced KIS] original query");
    expect(callout).toHaveTextContent("Mock");
  });

  it("renders loading and friendly API error states", async () => {
    let rejectSearch: ((reason: unknown) => void) | undefined;
    setupApi(
      () =>
        new Promise<Response>((_resolve, reject) => {
          rejectSearch = reject;
        }),
    );
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "query");
    await user.click(screen.getByRole("button", { name: "Search KIS" }));
    expect(await screen.findByText("Đang tìm trong fixture…")).toBeInTheDocument();

    rejectSearch?.(new TypeError("Network error"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Không thể kết nối tới backend",
    );
  });

  it("renders an explicit empty state", async () => {
    setupApi(() => jsonResponse(searchResponse("KIS", { empty: true })));
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "không có kết quả");
    await user.click(screen.getByRole("button", { name: "Search KIS" }));

    expect(await screen.findByText("Không tìm thấy candidate")).toBeInTheDocument();
  });

  it("aborts the previous request when a new search starts", async () => {
    const signals: AbortSignal[] = [];
    let callCount = 0;
    setupApi((init) => {
      callCount += 1;
      signals.push(init.signal as AbortSignal);
      if (callCount === 1) {
        return new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")));
        });
      }
      return jsonResponse(searchResponse("KIS", { empty: true }));
    });
    const user = userEvent.setup();
    renderApp();

    const query = await screen.findByLabelText(/^Query KIS/);
    await user.type(query, "first query");
    await user.click(screen.getByRole("button", { name: "Search KIS" }));
    await screen.findByText("Đang tìm trong fixture…");

    await user.clear(query);
    await user.type(query, "second query");
    await user.click(screen.getByRole("button", { name: "Search KIS again" }));

    await waitFor(() => expect(signals[0]?.aborted).toBe(true));
    expect(await screen.findByText("Không tìm thấy candidate")).toBeInTheDocument();
  });
});
