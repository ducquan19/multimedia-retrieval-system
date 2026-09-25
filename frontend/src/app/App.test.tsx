import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { KISQueryPlan, QueryType } from "../api/types";
import { App } from "./App";

const publicConfig = {
  min_top_k: 1,
  max_top_k: 500,
  default_top_k: 100,
  max_trake_events: 4,
  max_query_length: 4_000,
  max_answer_length: 4_000,
  model_choices: ["siglip"],
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function searchResponse(
  queryType: QueryType,
  options: { enhanced?: boolean; empty?: boolean; weights?: boolean } = {},
) {
  return {
    query_type: queryType,
    original_query: "original query",
    enhanced_query: options.enhanced ? "[Mock enhanced KIS] original query" : null,
    model_choices: ["siglip"],
    applied_weights: options.weights ? { w_vis: 1, w_asr: 0 } : null,
    warnings: [],
    ...(queryType === "TRAFFIC" ? { filtered_keyframes: 904 } : {}),
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
            objects: [{ label: "laptop", score: 0.97 }],
            similarity_score: 0.9821,
            answer: "",
          },
        ],
  };
}

type SearchHandler = (init: RequestInit) => Response | Promise<Response>;

const trafficOptions = {
  available: true,
  cameras: [
    {
      camera_id: "C001",
      name: "An Dương Vương - Lê Hồng Phong",
      streets: ["An Dương Vương", "Lê Hồng Phong"],
      video_ids: ["N001-V001", "N001-V002", "N001-V003"],
    },
    {
      camera_id: "C002",
      name: "Cộng Quỳnh - Bùi Viện",
      streets: ["Cộng Quỳnh", "Bùi Viện"],
      video_ids: ["N014-V001"],
    },
  ],
  dates: ["2026-06-10", "2026-06-15"],
  dayparts: ["morning", "midday", "night"],
  weathers: ["dry", "wet"],
};

const queryPlan: KISQueryPlan = {
  search_mode: "temporal_sequence",
  planner_model: "gemini-3.5-flash-lite",
  warnings: [],
  events: [
    {
      event_index: 1,
      source_span_vi: "tháo rời máy ảnh",
      visual_query_en: "a person disassembling a camera",
      asr_query_vi: null,
      importance: "anchor",
      confidence: 0.96,
      inferred: false,
    },
  ],
};

function setupApi(
  searchHandler: SearchHandler = () => jsonResponse(searchResponse("KIS")),
  planHandler: SearchHandler = () => jsonResponse(queryPlan),
) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    if (url.endsWith("/api/health")) return Promise.resolve(jsonResponse({ status: "ok" }));
    if (url.endsWith("/api/config")) return Promise.resolve(jsonResponse(publicConfig));
    if (url.endsWith("/api/search/kis/plan")) return Promise.resolve(planHandler(init));
    if (url.endsWith("/api/search")) return Promise.resolve(searchHandler(init));
    if (url.endsWith("/api/traffic/options")) return Promise.resolve(jsonResponse(trafficOptions));
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
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("App query workspace", () => {
  it("renders the mock shell and switches between TRAKE, KIS and TRAFFIC tabs", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();

    expect(await screen.findByLabelText(/^Query KIS/)).toBeInTheDocument();
    expect(screen.getByLabelText("Top-K")).toHaveAttribute("type", "number");
    expect(screen.getByLabelText("SigLIP-2")).toBeChecked();
    expect(screen.getByLabelText("BEiT-3")).not.toBeChecked();
    expect(screen.getByRole("textbox", { name: "Video ID" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open" })).toBeDisabled();

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "TRAKE",
      "KIS",
      "TRAFFIC",
    ]);

    await user.click(screen.getByRole("tab", { name: /TRAFFIC/ }));
    expect(screen.getByLabelText(/^Query TRAFFIC/)).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Traffic filters" })).toBeInTheDocument();
    expect(screen.queryByLabelText("ASR")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Query KIS/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /TRAKE/ }));
    expect(screen.getByLabelText(/^Main query TRAKE/)).toBeInTheDocument();
    expect(screen.getByLabelText("EVENT 1")).toBeInTheDocument();
    expect(screen.getByLabelText("EVENT 2")).toBeInTheDocument();
  });

  it("renders Top-K in the footer without a visible label", async () => {
    setupApi();
    renderApp();

    const topKInput = await screen.findByLabelText("Top-K");
    expect(topKInput).toHaveValue(100);
    expect(topKInput.closest(".workspace__footer")).not.toBeNull();
    expect(screen.queryByText("Top-K")).not.toBeInTheDocument();
  });

  it("toggles and remembers dark mode from the brand switch", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();

    const themeSwitch = await screen.findByRole("switch", { name: "Dark mode" });
    expect(themeSwitch).not.toBeChecked();
    expect(document.documentElement).toHaveAttribute("data-theme", "light");

    await user.click(themeSwitch);
    expect(themeSwitch).toBeChecked();
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(window.localStorage.getItem("aic-retrieval-theme")).toBe("dark");
  });

  it("keeps result controls and video lookup in one shared header", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();

    const header = await screen.findByRole("banner", { name: "Result tools" });
    expect(within(header).getByRole("textbox", { name: "Video ID" })).toBeInTheDocument();
    expect(within(header).queryByRole("combobox", { name: "Program" })).not.toBeInTheDocument();
    expect(within(header).queryByRole("checkbox", { name: "Group by video" })).not.toBeInTheDocument();

    await user.type(await screen.findByLabelText(/^Query KIS/), "query");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await within(header).findByRole("checkbox", { name: "Group by video" })).toBeInTheDocument();
    expect(within(header).getByText("KIS")).toBeInTheDocument();
    expect(within(header).getByRole("textbox", { name: "Video ID" })).toBeInTheDocument();
    expect(within(header).getByRole("combobox", { name: "Program" })).toHaveValue("ALL");
  });

  it("fills every TRAKE EVENT from one pasted E1/E2/... block", async () => {
    const fetchMock = setupApi(() => jsonResponse(searchResponse("TRAKE", { empty: true })));
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("tab", { name: /TRAKE/ }));
    await user.click(screen.getByLabelText(/^Main query TRAKE/));
    await user.paste("E1: xe buýt dừng lại\nE2: hành khách xuống xe\nE3: xe chạy đi\nE4: đèn đỏ");

    expect(screen.getByLabelText(/^Main query TRAKE/)).toHaveValue("");
    expect(screen.getByLabelText("EVENT count")).toHaveValue("4");
    expect(screen.getByLabelText("EVENT 1")).toHaveValue("xe buýt dừng lại");
    expect(screen.getByLabelText("EVENT 4")).toHaveValue("đèn đỏ");

    // A shorter paste into an EVENT box shrinks the count.
    await user.click(screen.getByLabelText("EVENT 2"));
    await user.paste("E1: a\nE2: b");
    expect(screen.getByLabelText("EVENT count")).toHaveValue("2");
    expect(screen.queryByLabelText("EVENT 3")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() =>
      expect(searchPayload(fetchMock)).toMatchObject({
        query_type: "TRAKE",
        events: [
          { event_index: 1, query: "a" },
          { event_index: 2, query: "b" },
        ],
      }),
    );
  });

  it("warns when a pasted block has more EVENTs than allowed", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("tab", { name: /TRAKE/ }));
    await user.click(screen.getByLabelText(/^Main query TRAKE/));
    await user.paste("E1: a\nE2: b\nE3: c\nE4: d\nE5: e");

    expect(screen.getByLabelText("EVENT count")).toHaveValue("4");
    expect(screen.getByRole("alert")).toHaveTextContent("Đã dán 5 EVENT, tối đa 4");
  });

  it("keeps an ordinary paste as plain text", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("tab", { name: /TRAKE/ }));
    await user.click(screen.getByLabelText(/^Main query TRAKE/));
    await user.paste("một đoạn mô tả");
    expect(screen.getByLabelText(/^Main query TRAKE/)).toHaveValue("một đoạn mô tả");
    expect(screen.getByLabelText("EVENT count")).toHaveValue("3");
  });

  it("restores a previous query from the history", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();

    const query = await screen.findByLabelText(/^Query KIS/);
    expect(screen.queryByRole("combobox", { name: "Query history" })).not.toBeInTheDocument();
    await user.type(query, "first query");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.clear(query);
    await user.type(query, "second query");
    await user.click(screen.getByRole("button", { name: "Search" }));

    const history = screen.getByRole("combobox", { name: "Query history" });
    expect(
      within(history)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Lịch sử truy vấn (2)", "second query", "first query"]);

    await user.selectOptions(history, "1");
    expect(query).toHaveValue("first query");
  });

  it("filters displayed results by program without changing the search payload", async () => {
    const response = searchResponse("KIS");
    response.results = [
      { ...response.results[0]!, result_id: "result-l21", video_id: "L21_V001" },
      { ...response.results[0]!, result_id: "result-l22", video_id: "L22_V001" },
      { ...response.results[0]!, result_id: "result-l25", video_id: "L25_V001" },
      { ...response.results[0]!, result_id: "result-l26", video_id: "L26_V001" },
      { ...response.results[0]!, result_id: "result-other", video_id: "L27_V001" },
      { ...response.results[0]!, result_id: "result-m", video_id: "M03_V002" },
      { ...response.results[0]!, result_id: "result-l23", video_id: "L23_V004" },
      { ...response.results[0]!, result_id: "result-s", video_id: "S01-V001" },
      { ...response.results[0]!, result_id: "result-n", video_id: "N014-V001" },
    ];
    const fetchMock = setupApi(() => jsonResponse(response));
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "query");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("L25_V001")).toBeInTheDocument();
    expect(screen.getByText("L26_V001")).toBeInTheDocument();
    expect(screen.getByText("L27_V001")).toBeInTheDocument();

    // Options come from the programs present in the results, with their counts.
    const program = screen.getByRole("combobox", { name: "Program" });
    expect(
      within(program)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "ALL",
      "Camera giao thông (1)",
      "Đua xe đạp (2)",
      "L27 (1)",
      "Món ngon mỗi ngày (1)",
      "Ôn thi THPT (1)",
      "Tin tức (3)",
    ]);

    await user.selectOptions(program, "L25");
    expect(screen.getByText("L25_V001")).toBeInTheDocument();
    expect(screen.queryByText("L26_V001")).not.toBeInTheDocument();
    expect(screen.queryByText("L27_V001")).not.toBeInTheDocument();

    await user.selectOptions(program, "L27");
    expect(screen.getByText("L27_V001")).toBeInTheDocument();
    expect(screen.queryByText("L25_V001")).not.toBeInTheDocument();

    await user.selectOptions(program, "CYCLING");
    expect(screen.getByText("L23_V004")).toBeInTheDocument();
    expect(screen.getByText("S01-V001")).toBeInTheDocument();
    expect(screen.queryByText("M03_V002")).not.toBeInTheDocument();

    await user.selectOptions(program, "TRAFFIC");
    expect(screen.getByText("N014-V001")).toBeInTheDocument();
    expect(screen.queryByText("S01-V001")).not.toBeInTheDocument();

    await user.selectOptions(program, "NEWS");
    expect(screen.getByText("L21_V001")).toBeInTheDocument();
    expect(screen.getByText("L22_V001")).toBeInTheDocument();
    expect(screen.getByText("M03_V002")).toBeInTheDocument();
    expect(screen.queryByText("L25_V001")).not.toBeInTheDocument();
    expect(searchPayload(fetchMock)).not.toHaveProperty("program");

    await user.click(screen.getByRole("button", { name: "Search" }));
    const keptProgram = await screen.findByRole("combobox", { name: "Program" });
    expect(keptProgram).toHaveValue("NEWS");
    expect(screen.getByText("L21_V001")).toBeInTheDocument();
    expect(screen.getByText("L22_V001")).toBeInTheDocument();
    expect(screen.queryByText("L25_V001")).not.toBeInTheDocument();
  });

  it("submits the typed KIS payload with shared controls", async () => {
    const fetchMock = setupApi(() => jsonResponse(searchResponse("KIS", { empty: true })));
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "người mở laptop");
    await user.clear(screen.getByLabelText("Top-K"));
    await user.type(screen.getByLabelText("Top-K"), "5");
    await user.click(screen.getByLabelText("ASR"));
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("Không tìm thấy candidate");
    expect(searchPayload(fetchMock)).toEqual({
      query_type: "KIS",
      query: "người mở laptop",
      top_k: 5,
      enhance_query: false,
      use_reranking: false,
      model_choices: ["siglip"],
      search_sources: { image: true, asr: true, object: false },
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

  it("submits a TRAFFIC query with metadata filters and no ASR source", async () => {
    const fetchMock = setupApi(() => jsonResponse(searchResponse("TRAFFIC", { empty: true })));
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("tab", { name: /TRAFFIC/ }));
    await user.type(screen.getByLabelText(/^Query TRAFFIC/), "xe buýt xanh rẽ trái");
    await user.type(await screen.findByLabelText(/^Tên đường/), "le hong phong");
    const cameras = screen.getByRole("list", { name: "Cameras" });
    expect(within(cameras).queryByText("Cộng Quỳnh - Bùi Viện")).not.toBeInTheDocument();
    await user.click(within(cameras).getByLabelText(/An Dương Vương - Lê Hồng Phong/));
    await user.click(screen.getByLabelText("Tối"));
    await user.click(screen.getByLabelText("Mưa / đường ướt"));
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("Không tìm thấy candidate");
    expect(searchPayload(fetchMock)).toEqual({
      query_type: "TRAFFIC",
      query: "xe buýt xanh rẽ trái",
      filters: { camera_ids: ["C001"], dates: [], dayparts: ["night"], weathers: ["wet"] },
      top_k: 100,
      enhance_query: false,
      use_reranking: false,
      model_choices: ["siglip"],
      search_sources: { image: true, asr: false, object: false },
    });
  });

  it("keeps hidden TRAKE event text and submits continuous event indices", async () => {
    const fetchMock = setupApi(() => jsonResponse(searchResponse("TRAKE", { empty: true })));
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("tab", { name: /TRAKE/ }));
    await user.type(screen.getByLabelText(/^Main query TRAKE/), "chuỗi nhảy cao");
    await user.type(screen.getByLabelText("EVENT 1"), "giậm nhảy");
    await user.type(screen.getByLabelText("EVENT 2"), "bay qua xà");

    await user.selectOptions(screen.getByLabelText("EVENT count"), "1");
    expect(screen.queryByLabelText("EVENT 2")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("EVENT count"), "2");
    expect(screen.getByLabelText("EVENT 2")).toHaveValue("bay qua xà");

    await user.selectOptions(screen.getByLabelText("EVENT count"), "3");
    await user.type(screen.getByLabelText("EVENT 3"), "tiếp đất");
    await user.click(screen.getByRole("button", { name: "Search" }));

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
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Chọn ít nhất một nguồn tìm kiếm");
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/search"))).toBe(
      false,
    );
  });

  it("shows original and enhanced query", async () => {
    setupApi(() => jsonResponse(searchResponse("KIS", { enhanced: true })));
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "original query");
    await user.click(screen.getByLabelText(/^Enhance query/));
    await user.click(screen.getByRole("button", { name: "Search" }));

    // Collapsed to one summary line by default, with the full text still readable.
    const expand = await screen.findByRole("button", { name: "Mở rộng search insight" });
    expect(expand).toHaveTextContent("Enhanced: [Mock enhanced KIS] original query");

    await user.click(expand);
    expect(screen.getByText("Enhanced:")).toBeInTheDocument();
    expect(screen.getByText("[Mock enhanced KIS] original query")).toBeInTheDocument();
    expect(window.localStorage.getItem("aic-search-insight-open")).toBe("true");

    await user.click(screen.getByRole("button", { name: "Thu gọn search insight" }));
    expect(screen.getByRole("button", { name: "Mở rộng search insight" })).toBeInTheDocument();
  });

  it(
    "plans and submits an editable advanced KIS query only when opted in",
    async () => {
      const fetchMock = setupApi(() =>
        jsonResponse(searchResponse("KIS", { enhanced: true, empty: true })),
      );
      const user = userEvent.setup();
      renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "tháo máy ảnh rồi lau lens");
    await user.click(screen.getByLabelText("Query Decomposition"));
    expect(screen.getByLabelText(/^Enhance query/)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Search" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Execute" }));
    const visualQuery = await screen.findByLabelText("Visual query EVENT 1");
    expect(visualQuery).toHaveValue("a person disassembling a camera");
    await user.clear(visualQuery);
    await user.type(visualQuery, "a detached camera lens on a purple towel");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("Không tìm thấy candidate");
    expect(screen.queryByText("Enhanced:")).not.toBeInTheDocument();
    expect(searchPayload(fetchMock)).toMatchObject({
      query_type: "KIS",
      query_understanding: true,
      enhance_query: false,
      query_plan: {
        search_mode: "temporal_sequence",
        events: [
          {
            event_index: 1,
            visual_query_en: "a detached camera lens on a purple towel",
            importance: "anchor",
          },
        ],
      },
    });

      await user.click(screen.getByRole("tab", { name: /TRAFFIC/ }));
      expect(screen.queryByLabelText("Query Decomposition")).not.toBeInTheDocument();
    },
    15_000,
  );

  it("shows applied weights only for a search submitted with enhancement", async () => {
    setupApi(() => jsonResponse(searchResponse("KIS", { weights: true })));
    const user = userEvent.setup();
    renderApp();

    await user.type(await screen.findByLabelText(/^Query KIS/), "visual query");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByRole("checkbox", { name: "Group by video" });
    expect(screen.queryByText("VIS: 1.00")).not.toBeInTheDocument();

    await user.click(screen.getByLabelText(/^Enhance query/));
    await user.click(screen.getByRole("button", { name: "Search" }));
    // Weight chips stay visible in the collapsed summary line.
    expect(await screen.findByText("VIS: 1.00")).toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByText("Đang tìm kiếm…")).toBeInTheDocument();

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
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("Không tìm thấy candidate")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Program" })).not.toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText("Đang tìm kiếm…");

    await user.clear(query);
    await user.type(query, "second query");
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(signals[0]?.aborted).toBe(true));
    // Wait until the new loading state appears (could be instantaneous or replacing)
    expect(await screen.findByText("Không tìm thấy candidate")).toBeInTheDocument();
  });
});
