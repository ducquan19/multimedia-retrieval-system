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

    await user.click(screen.getByRole("button", { name: "Nộp DRES" }));

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

    await user.click(screen.getByRole("button", { name: "Nộp DRES" }));
    await waitFor(() => expect(screen.getByLabelText("Start (ms)")).toHaveValue(20200));
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));
    expect(await screen.findByText("CORRECT")).toBeInTheDocument();
    unmount();

    // Reopened on the same frame: that exact answer is blocked before any request.
    renderModal(target);
    await user.click(screen.getByRole("button", { name: "Nộp DRES" }));
    await waitFor(() => expect(screen.getByLabelText("Start (ms)")).toHaveValue(20200));
    expect(screen.getByRole("note")).toHaveTextContent(
      /Đáp án này đã nộp lúc .*\(CORRECT\).*không thể nộp lại/,
    );
    expect(screen.getByRole("button", { name: "Xác nhận nộp" })).toBeDisabled();

    // Another time in the same video is allowed, with a reminder of the earlier answer.
    await user.clear(screen.getByLabelText("End (ms)"));
    await user.type(screen.getByLabelText("End (ms)"), "21000");
    expect(screen.getByRole("note")).toHaveTextContent(
      /Đã nộp L01_V001 1 lần .*CORRECT.*20200–20200 ms/,
    );
    expect(screen.getByRole("button", { name: "Xác nhận nộp" })).toBeEnabled();
  });

  it("keeps the fields editable after a WRONG answer and resubmits without closing", async () => {
    const wrong = {
      accepted: true,
      status_code: 200,
      submission: "WRONG",
      description: "Submission incorrect",
      body: {},
    };
    const fetchMock = setupApi([jsonResponse(wrong)]);
    const user = userEvent.setup();
    renderModal({
      kind: "single",
      videoId: "L01_V001",
      frameId: 505,
      defaultMode: "KIS",
      answer: "",
    });

    await user.click(screen.getByRole("button", { name: "Nộp DRES" }));
    const start = await screen.findByLabelText("Start (ms)");
    await waitFor(() => expect(start).toHaveValue(20200));
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("WRONG");
    expect(result).toHaveClass("dres-panel__result--fail");
    expect(start).toBeEnabled();
    // The WRONG answer itself cannot be sent again, only an edited one.
    expect(screen.getByRole("button", { name: "Nộp lại" })).toBeDisabled();
    expect(screen.getByRole("note")).toHaveTextContent("không thể nộp lại");

    await user.clear(start);
    await user.type(start, "19000");
    await user.clear(screen.getByLabelText("End (ms)"));
    await user.type(screen.getByLabelText("End (ms)"), "22000");
    expect(screen.getByRole("status")).toHaveTextContent("Lần nộp trước: WRONG");
    await user.click(screen.getByRole("button", { name: "Nộp lại" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("CORRECT"));
    expect(screen.getByRole("status")).toHaveClass("dres-panel__result--ok");
    expect(submitPayloads(fetchMock).map((payload) => payload.answerSets)).toEqual([
      [{ answers: [{ mediaItemName: "L01_V001", start: "20200", end: "20200" }] }],
      [{ answers: [{ mediaItemName: "L01_V001", start: "19000", end: "22000" }] }],
    ]);
    // A CORRECT verdict ends the submission: nothing left to resend.
    expect(screen.getByLabelText("Start (ms)")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Nộp lại" })).not.toBeInTheDocument();
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

    await user.click(screen.getByRole("button", { name: "Nộp DRES" }));
    await user.click(screen.getByRole("radio", { name: "VQA" }));
    await waitFor(() => expect(screen.getByLabelText("Time (ms)")).toHaveValue(20200));
    expect(screen.getByLabelText("Đáp án VQA")).toHaveValue("3");
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

    await user.click(screen.getByRole("button", { name: "Nộp DRES" }));
    await user.click(screen.getByRole("radio", { name: "VQA" }));
    await waitFor(() => expect(screen.getByLabelText("Time (ms)")).toHaveValue(20200));
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Task đang chạy là KIS: DRES chỉ nhận mediaItemName + start/end, không nhận QA.",
    );
  });

  it("never resends an answer the backend reports as already submitted", async () => {
    const fetchMock = setupApi([
      jsonResponse(
        { detail: "Đáp án này đã được nộp cho evaluation này, không thể nộp lại." },
        409,
      ),
    ]);
    const user = userEvent.setup();
    renderModal(
      { kind: "trake", videoId: "L01_V001", frameIds: [10, 20, 30], eventIndex: 2 },
      20,
    );

    await user.click(screen.getByRole("button", { name: "Nộp DRES" }));
    await waitFor(() => expect(screen.getByLabelText("Evaluation")).toHaveValue("ev1"));
    expect(screen.getByLabelText("Frame IDs")).toHaveValue("10,20,30");
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));

    expect(await screen.findByText("Đã nộp đáp án này")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Vẫn nộp lại" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nộp lại" })).toBeDisabled();

    // A different answer is a new submission and goes through.
    await user.clear(screen.getByLabelText("Frame IDs"));
    await user.type(screen.getByLabelText("Frame IDs"), "10,25,30");
    await user.click(screen.getByRole("button", { name: "Nộp lại" }));
    await screen.findByText("CORRECT");

    expect(submitPayloads(fetchMock)).toEqual([
      { evaluation_id: "ev1", answerSets: [{ answers: [{ text: "TR-L01_V001-10,20,30" }] }] },
      { evaluation_id: "ev1", answerSets: [{ answers: [{ text: "TR-L01_V001-10,25,30" }] }] },
    ]);
  });
});
