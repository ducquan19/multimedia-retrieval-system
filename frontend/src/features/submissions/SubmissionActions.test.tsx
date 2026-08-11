import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SubmissionRequest } from "../../api/types";
import { SubmissionActions } from "./SubmissionActions";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SubmissionActions", () => {
  it("reflects the sanitized backend filename and sends identical preview/download payloads", async () => {
    const payloads: SubmissionRequest[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
        payloads.push(JSON.parse(String(init.body)) as SubmissionRequest);
        if (String(input).endsWith("/render")) {
          return new Response(
            JSON.stringify({
              content: "L01_V001,505\r\n",
              filename: "evil.csv",
              row_count: 1,
              warnings: [],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response("L01_V001,505\r\n", {
          status: 200,
          headers: {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition":
              "attachment; filename=\"evil.csv\"; filename*=UTF-8''evil.csv",
          },
        });
      }),
    );
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:submission"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const user = userEvent.setup();
    const buildPayload = (filename: string): SubmissionRequest => ({
      query_type: "KIS",
      filename,
      rows: [{ video_id: "L01_V001", frame_id: 505 }],
    });

    render(
      <SubmissionActions
        queryType="KIS"
        rowCount={1}
        orderChanged={false}
        stateVersion="initial"
        onResetOrder={() => undefined}
        buildPayload={buildPayload}
      />,
    );

    const filenameInput = screen.getByLabelText("Filename");
    await user.clear(filenameInput);
    await user.type(filenameInput, "../../evil.csv");
    await user.click(screen.getByRole("button", { name: "Preview submission" }));

    expect(await screen.findByRole("dialog", { name: "evil.csv" })).toBeInTheDocument();
    expect(screen.getByText(/Backend filename:/)).toHaveTextContent("evil.csv");
    await user.click(screen.getByRole("button", { name: "Close submission preview" }));
    expect(screen.getByRole("button", { name: "Preview submission" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Download submission" }));

    expect(await screen.findByText(/Backend filename:/)).toHaveTextContent("evil.csv");
    expect(payloads).toHaveLength(2);
    expect(payloads[1]).toEqual(payloads[0]);
    expect(payloads[0]).toMatchObject({ filename: "../../evil.csv" });
  });

  it("shows an immediate empty-answer warning and disables download while pending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>(() => {
            // Keep the request pending for the button-state assertion.
          }),
      ),
    );
    const user = userEvent.setup();
    render(
      <SubmissionActions
        queryType="VQA"
        rowCount={1}
        emptyAnswerCount={1}
        orderChanged={false}
        stateVersion="initial"
        onResetOrder={() => undefined}
        buildPayload={(filename) => ({
          query_type: "VQA",
          filename,
          rows: [{ video_id: "L01", frame_id: 1, answer: "" }],
        })}
      />,
    );

    expect(screen.getByText("1 empty VQA answer")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Download submission" }));
    expect(screen.getByRole("button", { name: "Downloading…" })).toBeDisabled();
  });

  it("cancels an in-flight preview when ordered result state changes", async () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init: RequestInit = {}) => {
        const signal = init.signal as AbortSignal;
        signals.push(signal);
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener("abort", () =>
            reject(new DOMException("Request cancelled", "AbortError")),
          );
        });
      }),
    );
    const user = userEvent.setup();
    const props = {
      queryType: "KIS" as const,
      rowCount: 1,
      orderChanged: false,
      onResetOrder: () => undefined,
      buildPayload: (filename: string): SubmissionRequest => ({
        query_type: "KIS",
        filename,
        rows: [{ video_id: "L01", frame_id: 1 }],
      }),
    };
    const { rerender } = render(
      <SubmissionActions {...props} stateVersion="order-a" />,
    );

    await user.click(screen.getByRole("button", { name: "Preview submission" }));
    expect(screen.getByRole("button", { name: "Preparing preview…" })).toBeDisabled();

    rerender(<SubmissionActions {...props} stateVersion="order-b" />);

    expect(signals[0]?.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Preview submission" })).toBeEnabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
