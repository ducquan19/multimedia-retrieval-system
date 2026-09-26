import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ResultDetailModal } from "../results/ResultDetailModal";
import type { SubmitTarget } from "./DresSubmitPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function setupApi(submitResponses: Response[] = []) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init: RequestInit = {}) => {
    void _init;
    const url = String(input);
    if (url.endsWith("/api/dres/evaluations")) {
      return Promise.resolve(
        jsonResponse([
          { id: "old", name: "Warm-up", type: "SYNCHRONOUS", status: "ENDED" },
          { id: "ev1", name: "Round 1", type: "SYNCHRONOUS", status: "ACTIVE" },
        ]),
      );
    }
    if (url.includes("/api/videos/L01_V001/source")) {
      return Promise.resolve(
        jsonResponse({ video_id: "L01_V001", url: "/v.mp4", source: "remote", fps: 25 }),
      );
    }
    if (url.endsWith("/api/dres/submit")) {
      return Promise.resolve(
        submitResponses.shift() ??
          jsonResponse({
            accepted: true,
            status_code: 200,
            submission: "CORRECT",
            description: "Submission correct",
            body: {},
          }),
      );
    }
    return Promise.resolve(jsonResponse({ detail: "Not found" }, 404));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function submitPayloads(fetchMock: ReturnType<typeof setupApi>) {
  return fetchMock.mock.calls
    .filter(([input]) => String(input).endsWith("/api/dres/submit"))
    .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);
}

function renderModal(submitTarget: SubmitTarget, frameId = 505) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ResultDetailModal
        result={{
          video_id: "L01_V001",
          frame_id: frameId,
          keyframe_url: "/media/keyframes/frame.jpg",
          segment_id: "L01_V001_S00001",
          asr_text: "",
          objects: [],
          similarity_score: 0.9,
        }}
        onClose={() => undefined}
        submitTarget={submitTarget}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("DRES submission", () => {
  it("submits an edited KIS time range only after confirmation", async () => {
    const fetchMock = setupApi();
    const user = userEvent.setup();
    renderModal({
      kind: "single",
      videoId: "L01_V001",
      frameId: 505,
      defaultMode: "KIS",
      answer: "",
    });

    await user.click(screen.getByRole("button", { name: "Submit DRES" }));

    const start = await screen.findByLabelText("Start (ms)");
    await waitFor(() => expect(start).toHaveValue(20200));
    expect(screen.getByLabelText("Evaluation")).toHaveValue("ev1");
    expect(submitPayloads(fetchMock)).toHaveLength(0);

    await user.clear(start);
    await user.type(start, "20000");
    await user.clear(screen.getByLabelText("End (ms)"));
    await user.type(screen.getByLabelText("End (ms)"), "21000");
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));

    expect(await screen.findByText("CORRECT")).toBeInTheDocument();
    expect(submitPayloads(fetchMock)).toEqual([
      {
        evaluation_id: "ev1",
        answerSets: [{ answers: [{ mediaItemName: "L01_V001", start: "20000", end: "21000" }] }],
        allow_duplicate: false,
      },
    ]);
  });

  it("logs each submission and warns before submitting the same video again", async () => {
    setupApi();
    const user = userEvent.setup();
    const target: SubmitTarget = {
      kind: "single",
      videoId: "L01_V001",
      frameId: 505,
      defaultMode: "KIS",
      answer: "",
    };
    const { unmount } = renderModal(target);

    await user.click(screen.getByRole("button", { name: "Submit DRES" }));
    await waitFor(() => expect(screen.getByLabelText("Start (ms)")).toHaveValue(20200));
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));
    expect(await screen.findByText("CORRECT")).toBeInTheDocument();
    unmount();

    renderModal(target);
    await user.click(screen.getByRole("button", { name: "Submit DRES" }));
    expect(await screen.findByRole("note")).toHaveTextContent(
      /Đã nộp L01_V001 1 lần .*CORRECT.*20200–20200 ms/,
    );
  });

  it("offers a VQA submission from a KIS result with the typed answer", async () => {
    const fetchMock = setupApi();
    const user = userEvent.setup();
    renderModal({
      kind: "single",
      videoId: "L01_V001",
      frameId: 505,
      defaultMode: "KIS",
      answer: "3",
    });

    await user.click(screen.getByRole("button", { name: "Submit DRES" }));
    await user.click(screen.getByRole("radio", { name: "VQA" }));
    await waitFor(() => expect(screen.getByLabelText("Time (ms)")).toHaveValue(20200));
    expect(screen.getByLabelText("VQA answer")).toHaveValue("3");
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));

    await screen.findByText("CORRECT");
    expect(submitPayloads(fetchMock)[0]).toMatchObject({
      answerSets: [{ answers: [{ text: "QA-3-L01_V001-20200" }] }],
    });
  });

  it("explains a QA answer rejected by the temporal filter of a KIS task", async () => {
    setupApi([
      jsonResponse({
        accepted: false,
        status_code: 412,
        submission: null,
        description:
          "Submission c5d77bb8 was rejected by filter: Submission does include non-temporal information.",
        body: {},
      }),
    ]);
    const user = userEvent.setup();
    renderModal({
      kind: "single",
      videoId: "L01_V001",
      frameId: 505,
      defaultMode: "KIS",
      answer: "13",
    });

    await user.click(screen.getByRole("button", { name: "Submit DRES" }));
    await user.click(screen.getByRole("radio", { name: "VQA" }));
    await waitFor(() => expect(screen.getByLabelText("Time (ms)")).toHaveValue(20200));
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Task đang chạy là KIS: DRES chỉ nhận mediaItemName + start/end, không nhận QA.",
    );
  });

  it("submits TRAKE frame IDs and asks before resending a duplicate", async () => {
    const fetchMock = setupApi([
      jsonResponse(
        { detail: "This exact answer was already submitted to this evaluation." },
        409,
      ),
    ]);
    const user = userEvent.setup();
    renderModal(
      { kind: "trake", videoId: "L01_V001", frameIds: [10, 20, 30], eventIndex: 2 },
      20,
    );

    await user.click(screen.getByRole("button", { name: "Submit DRES" }));
    await waitFor(() => expect(screen.getByLabelText("Evaluation")).toHaveValue("ev1"));
    expect(screen.getByLabelText("Frame IDs")).toHaveValue("10,20,30");
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));

    expect(await screen.findByText("Đã nộp đáp án này")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Vẫn nộp lại" }));
    await screen.findByText("CORRECT");

    expect(submitPayloads(fetchMock)).toEqual([
      {
        evaluation_id: "ev1",
        answerSets: [{ answers: [{ text: "TR-L01_V001-10,20,30" }] }],
        allow_duplicate: false,
      },
      {
        evaluation_id: "ev1",
        answerSets: [{ answers: [{ text: "TR-L01_V001-10,20,30" }] }],
        allow_duplicate: true,
      },
    ]);
  });
});
