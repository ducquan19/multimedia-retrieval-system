import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DresSubmitResponse } from "../../api/types";
import { submissionTone } from "../submission/DresSubmitPanel";
import { renderWithQuery as render } from "../../test/renderWithQuery";
import { VideoLookup } from "./VideoLookup";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function verdict(submission: string | null, accepted = true): DresSubmitResponse {
  return { accepted, status_code: 200, submission, description: null, body: { answerSets: [] } };
}

function setupApi(submitVerdict: string) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init: RequestInit = {}) => {
    void _init;
    const url = String(input);
    if (url.endsWith("/api/dres/evaluations")) {
      return Promise.resolve(jsonResponse([{ id: "ev1", name: "Final", type: null, status: "ACTIVE" }]));
    }
    if (url.endsWith("/api/dres/submit")) {
      return Promise.resolve(jsonResponse(verdict(submitVerdict)));
    }
    if (url.endsWith("/api/dres/submissions")) return Promise.resolve(jsonResponse([]));
    return Promise.resolve(
      jsonResponse({ video_id: "L21_V003", url: "/v.mp4", source: "local", fps: 25 }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  return fetchMock;
}

function submitPayloads(fetchMock: ReturnType<typeof setupApi>) {
  return fetchMock.mock.calls
    .filter(([input]) => String(input).endsWith("/api/dres/submit"))
    .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);
}

async function openVideoAtFrame(user: ReturnType<typeof userEvent.setup>, frame: number) {
  render(<VideoLookup />);
  await user.type(screen.getByRole("textbox", { name: "Mã video" }), "L21_V003");
  await user.type(screen.getByRole("spinbutton", { name: "Frame" }), String(frame));
  await user.click(screen.getByRole("button", { name: "Mở video" }));
  const fallback = await screen.findByText("Trình duyệt không phát được video này.");
  const video = fallback.closest("video");
  if (!(video instanceof HTMLVideoElement)) throw new Error("Expected video player");
  Object.defineProperty(video, "duration", { configurable: true, value: 100 });
  fireEvent.loadedMetadata(video);
  return video;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("submissionTone", () => {
  it("is green only for CORRECT, red for WRONG or a rejection, amber otherwise", () => {
    expect(submissionTone(verdict("CORRECT"))).toBe("ok");
    expect(submissionTone(verdict("WRONG"))).toBe("fail");
    expect(submissionTone(verdict("CORRECT", false))).toBe("fail");
    expect(submissionTone(verdict("INDETERMINATE"))).toBe("pending");
    expect(submissionTone(verdict(null))).toBe("pending");
  });
});

describe("Submitting from free video viewing", () => {
  it("submits KIS at the frame on screen and shows a WRONG verdict in red", async () => {
    const fetchMock = setupApi("WRONG");
    const user = userEvent.setup();
    await openVideoAtFrame(user, 125);

    await user.click(screen.getByRole("button", { name: "Nộp DRES" }));
    await waitFor(() => expect(screen.getByLabelText("Start (ms)")).toHaveValue(5000));
    await user.click(screen.getByRole("button", { name: "Xác nhận nộp" }));

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("WRONG");
    expect(result).toHaveClass("dres-panel__result--fail");
    expect(submitPayloads(fetchMock)[0]).toMatchObject({
      answerSets: [{ answers: [{ mediaItemName: "L21_V003", start: "5000", end: "5000" }] }],
    });
  });

  it("builds a TRAKE answer by adding frames while watching", async () => {
    const fetchMock = setupApi("CORRECT");
    const user = userEvent.setup();
    const video = await openVideoAtFrame(user, 125);

    await user.click(screen.getByRole("button", { name: "Nộp DRES" }));
    const panel = screen.getByRole("region", { name: "Nộp DRES" });
    await user.click(within(panel).getByRole("radio", { name: "TRAKE" }));
    expect(within(panel).getByLabelText("Frame IDs")).toHaveValue("125");

    video.currentTime = 10;
    fireEvent.timeUpdate(video);
    await user.click(
      within(panel).getByRole("button", { name: "Thêm frame đang xem (250) vào TRAKE" }),
    );
    video.currentTime = 20;
    fireEvent.timeUpdate(video);
    await user.click(
      within(panel).getByRole("button", { name: "Thêm frame đang xem (500) vào TRAKE" }),
    );
    expect(within(panel).getByLabelText("Frame IDs")).toHaveValue("125,250,500");

    await user.click(within(panel).getByRole("button", { name: "Xác nhận nộp" }));
    const result = await screen.findByRole("status");
    expect(result).toHaveClass("dres-panel__result--ok");
    expect(submitPayloads(fetchMock)[0]).toMatchObject({
      answerSets: [{ answers: [{ text: "TR-L21_V003-125,250,500" }] }],
    });
  });
});
