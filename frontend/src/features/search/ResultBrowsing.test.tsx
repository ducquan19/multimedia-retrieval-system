import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";

const config = {
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

function result(id: string, video: string, segment: string, frame: number, score: number) {
  return {
    result_id: id,
    rank: 0,
    video_id: video,
    frame_id: frame,
    keyframe_url: `/media/keyframes/${id}.jpg`,
    image_path: `keyframes/${id}.jpg`,
    segment_id: segment,
    asr_text: "",
    objects: [],
    similarity_score: score,
    answer: "",
    time_ms: null,
    camera_name: null,
    clock_time: null,
    weather: null,
  };
}

const kisResponse = {
  query_type: "KIS",
  original_query: "query",
  enhanced_query: null,
  model_choices: ["siglip"],
  applied_weights: null,
  warnings: [],
  query_plan: null,
  auto_object_query: [],
  results: [
    result("L01_V001/1", "L01_V001", "L01_V001_S1", 100, 0.9),
    result("L01_V001/2", "L01_V001", "L01_V001_S1", 125, 0.8),
    result("L02_V001/1", "L02_V001", "L02_V001_S4", 900, 0.7),
    result("L03_V001/1", "L03_V001", "L03_V001_S2", 50, 0.6),
  ],
};

const similarResponse = {
  query_type: "SIMILAR",
  video_id: "L02_V001",
  frame_id: 900,
  model_choices: ["siglip"],
  warnings: [],
  results: [
    result("L05_V002/1", "L05_V002", "L05_V002_S1", 10, 0.97),
    result("L06_V001/1", "L06_V001", "L06_V001_S9", 20, 0.95),
  ],
};

function setupApi() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    void _init;
    const url = String(input);
    if (url.endsWith("/api/config")) return jsonResponse(config);
    if (url.endsWith("/api/search/similar")) return jsonResponse(similarResponse);
    if (url.endsWith("/api/search")) return jsonResponse(kisResponse);
    if (url.endsWith("/api/dres/submissions")) return jsonResponse([]);
    return jsonResponse({ detail: "Not found" }, 404);
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

async function searchKis(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText(/^Truy vấn KIS/), "query");
  await user.click(screen.getByRole("button", { name: "Tìm kiếm" }));
  await screen.findAllByTestId("result-card");
}

function cardVideos(): string[] {
  return screen
    .getAllByTestId("result-card")
    .map((card) => within(card).getByText(/^L\d{2}_V\d{3}$/).textContent ?? "");
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("Browsing results", () => {
  it("keeps one frame per shot and remembers the choice", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();
    await searchKis(user);
    expect(cardVideos()).toEqual(["L01_V001", "L01_V001", "L02_V001", "L03_V001"]);

    await user.click(screen.getByRole("checkbox", { name: "1 ảnh mỗi shot" }));

    expect(cardVideos()).toEqual(["L01_V001", "L02_V001", "L03_V001"]);
    expect(screen.getByRole("button", { name: /L01_V001, frame 100, gộp thêm 1 ảnh/ })).toBeVisible();
    expect(screen.getByText(/3 shot/)).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem("aic-result-view") ?? "{}")).toMatchObject({
      collapseShots: true,
    });
  });

  it("marks opened frames and hides a ruled-out video", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();
    await searchKis(user);

    await user.click(screen.getByRole("button", { name: "Mở chi tiết L01_V001, frame 100" }));
    await user.keyboard("{Escape}");
    expect(
      screen.getByRole("button", { name: "Mở chi tiết L01_V001, frame 100, đã xem" }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Mở chi tiết L02_V001, frame 900" }));
    await user.click(screen.getByRole("button", { name: "Ẩn video" }));

    expect(cardVideos()).toEqual(["L01_V001", "L01_V001", "L03_V001"]);
    expect(screen.getByRole("status")).toHaveTextContent("Đã ẩn 1 video: L02_V001");
    await user.click(screen.getByRole("button", { name: "Hiện lại" }));
    expect(cardVideos()).toContain("L02_V001");
  });

  it("searches frames similar to the one open and returns to the text results", async () => {
    const fetchMock = setupApi();
    const user = userEvent.setup();
    renderApp();
    await searchKis(user);

    await user.click(screen.getByRole("button", { name: "Mở chi tiết L02_V001, frame 900" }));
    await user.click(screen.getByRole("button", { name: "Tìm ảnh tương tự" }));

    await waitFor(() => expect(cardVideos()).toEqual(["L05_V002", "L06_V001"]));
    const similarCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/search/similar"),
    );
    expect(JSON.parse(String(similarCall?.[1]?.body))).toEqual({
      video_id: "L02_V001",
      frame_id: 900,
      top_k: 100,
      model_choices: ["siglip"],
      include_traffic: false,
    });
    expect(screen.getByText(/Ảnh giống/)).toHaveTextContent("Ảnh giống L02_V001 frame 900");

    await user.click(screen.getByRole("button", { name: "← Về kết quả tìm" }));
    expect(cardVideos()).toEqual(["L01_V001", "L01_V001", "L02_V001", "L03_V001"]);
  });

  it("moves between frames with the arrow keys", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();
    await searchKis(user);

    screen.getByRole("button", { name: "Mở chi tiết L01_V001, frame 100" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("button", { name: "Mở chi tiết L01_V001, frame 125" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("button", { name: "Mở chi tiết L03_V001, frame 50" })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("button", { name: "Mở chi tiết L01_V001, frame 100" })).toHaveFocus();
  });

  it("opens the shortcut list with ? and jumps to the query with /", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();
    const query = await screen.findByLabelText(/^Truy vấn KIS/);

    await user.keyboard("?");
    expect(screen.getByRole("dialog", { name: "Phím tắt" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Phím tắt" })).not.toBeInTheDocument();

    await user.keyboard("/");
    expect(query).toHaveFocus();
    // Typed into the query, "?" is just a character.
    await user.keyboard("?");
    expect(query).toHaveValue("?");
    expect(screen.queryByRole("dialog", { name: "Phím tắt" })).not.toBeInTheDocument();
  });

  it("changes the frame size of the sheet", async () => {
    setupApi();
    const user = userEvent.setup();
    renderApp();
    await searchKis(user);

    await user.click(screen.getByRole("radio", { name: /Ảnh nhỏ/ }));

    expect(document.querySelector(".sheet__content")).toHaveAttribute("data-frame-size", "S");
  });
});
