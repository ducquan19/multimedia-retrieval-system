import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  TRAKEEventResult,
  TRAKESearchResponse,
  TRAKESearchResult,
} from "../../api/types";
import { TrakeResultInspector } from "./TrakeResultInspector";
import { createResultEditorState, resultEditorReducer } from "./resultState";

function event(eventIndex: number, frameId: number, label: string): TRAKEEventResult {
  return {
    event_index: eventIndex,
    frame_id: frameId,
    keyframe_url: `/media/keyframes/${label}.jpg`,
    segment_id: `segment-${label}`,
    asr_text: `ASR transcript ${label}`,
    ocr_text: "",
    objects: [],
    similarity_score: 0.9 - eventIndex / 100,
  };
}

const results: TRAKESearchResult[] = [
  {
    result_id: "trake-a",
    rank: 1,
    video_id: "L01_V001",
    similarity_score: 0.95,
    events: [event(1, 101, "a1"), event(2, 151, "a2"), event(3, 203, "a3")],
  },
  {
    result_id: "trake-b",
    rank: 2,
    video_id: "L02_V002",
    similarity_score: 0.91,
    events: [event(1, 305, "b1"), event(2, 390, "b2"), event(3, 480, "b3")],
  },
];

function response(nextResults = results): TRAKESearchResponse {
  return {
    query_type: "TRAKE",
    original_query: "three events in sequence",
    enhanced_query: null,
    retrieval_mode: "mock",
    results: nextResults,
  };
}

function rows(): HTMLElement[] {
  return screen.getAllByTestId("trake-row");
}

afterEach(() => vi.unstubAllGlobals());

describe("TrakeResultInspector", () => {
  it("renders exactly N event cells in fixed Event 1..N order", () => {
    render(<TrakeResultInspector response={response()} expectedEventCount={3} />);

    for (const row of rows()) {
      const cells = within(row).getAllByTestId("trake-event-cell");
      expect(cells).toHaveLength(3);
      expect(cells.map((cell) => cell.getAttribute("aria-label"))).toEqual([
        "Event 1",
        "Event 2",
        "Event 3",
      ]);
    }
  });

  it("reorders complete rows while preserving their event sequence", async () => {
    const user = userEvent.setup();
    render(<TrakeResultInspector response={response()} expectedEventCount={3} />);

    await user.click(screen.getByRole("button", { name: "Move result trake-b up" }));

    expect(within(rows()[0]!).getByText("L02_V002")).toBeInTheDocument();
    expect(
      within(rows()[0]!).getAllByTestId("trake-event-cell").map((cell) =>
        within(cell).getByText(/^(305|390|480)$/).textContent,
      ),
    ).toEqual(["305", "390", "480"]);
    expect(
      within(rows()[0]!).getByRole("article", { name: "Rank 1, L02_V002" }),
    ).toBeInTheDocument();
  });

  it("uses result_id for the drag reorder state", () => {
    const initial = createResultEditorState(results);
    const moved = resultEditorReducer(initial, {
      type: "move",
      activeId: "trake-b",
      overId: "trake-a",
    });

    expect(moved.order).toEqual(["trake-b", "trake-a"]);
  });

  it("resets rows to the original API order", async () => {
    const user = userEvent.setup();
    render(<TrakeResultInspector response={response()} expectedEventCount={3} />);

    await user.click(screen.getByRole("button", { name: "Move result trake-b up" }));
    await user.click(screen.getByRole("button", { name: "Reset order" }));

    expect(within(rows()[0]!).getByText("L01_V001")).toBeInTheDocument();
    expect(within(rows()[1]!).getByText("L02_V002")).toBeInTheDocument();
  });

  it("exports each reordered TRAKE row with exactly N fixed frame IDs", async () => {
    const payloads: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init: RequestInit = {}) => {
        payloads.push(JSON.parse(String(init.body)) as Record<string, unknown>);
        return new Response(
          JSON.stringify({
            content: "L02_V002,305,390,480\r\nL01_V001,101,151,203\r\n",
            filename: "trake_submission.csv",
            row_count: 2,
            warnings: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }),
    );
    const user = userEvent.setup();
    render(<TrakeResultInspector response={response()} expectedEventCount={3} />);

    await user.click(screen.getByRole("button", { name: "Move result trake-b up" }));
    await user.click(screen.getByRole("button", { name: "Preview submission" }));

    expect(await screen.findByTestId("submission-preview-content")).toHaveTextContent(
      "L02_V002,305,390,480",
    );
    expect(payloads[0]).toMatchObject({
      query_type: "TRAKE",
      event_count: 3,
      rows: [
        { video_id: "L02_V002", frame_ids: [305, 390, 480] },
        { video_id: "L01_V001", frame_ids: [101, 151, 203] },
      ],
    });
  });

  it("opens the shared event modal with ASR and restores focus", async () => {
    const user = userEvent.setup();
    render(<TrakeResultInspector response={response()} expectedEventCount={3} />);
    const trigger = screen.getByRole("button", {
      name: "Open Event 2 details for L01_V001, frame 151",
    });

    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "L01_V001" })).toHaveTextContent(
      "ASR transcript a2",
    );
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it.each([
    {
      name: "wrong event count",
      malformed: [{ ...results[0]!, events: results[0]!.events.slice(0, 2) }],
      message: "has 2 events; expected 3",
    },
    {
      name: "non-continuous event_index",
      malformed: [
        {
          ...results[0]!,
          events: [event(1, 101, "a1"), event(3, 151, "a2"), event(4, 203, "a3")],
        },
      ],
      message: "event_index must be continuous from 1",
    },
    {
      name: "event from another video",
      malformed: [
        {
          ...results[0]!,
          events: [
            event(1, 101, "a1"),
            { ...event(2, 151, "a2"), video_id: "L99_V999" },
            event(3, 203, "a3"),
          ],
        },
      ],
      message: "belongs to L99_V999, not L01_V001",
    },
  ])("rejects a malformed row with $name", ({ malformed, message }) => {
    render(<TrakeResultInspector response={response(malformed)} expectedEventCount={3} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Cannot display malformed TRAKE results",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByTestId("trake-row")).not.toBeInTheDocument();
  });

  it("exposes a horizontal overflow container for event columns", () => {
    render(<TrakeResultInspector response={response()} expectedEventCount={3} />);

    expect(screen.getByTestId("trake-scroll-container")).toHaveStyle({
      overflowX: "auto",
    });
  });
});
