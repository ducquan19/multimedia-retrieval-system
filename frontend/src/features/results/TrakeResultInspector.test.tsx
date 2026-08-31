import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type {
  TRAKEEventResult,
  TRAKESearchResponse,
  TRAKESearchResult,
} from "../../api/types";
import { TrakeResultInspector } from "./TrakeResultInspector";

function event(eventIndex: number, frameId: number, label: string): TRAKEEventResult {
  return {
    event_index: eventIndex,
    frame_id: frameId,
    keyframe_url: `/media/keyframes/${label}.jpg`,
    segment_id: `segment-${label}`,
    asr_text: `ASR transcript ${label}`,
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
    model_choices: ["siglip", "beit3"],
    applied_weights: null,
    warnings: [],
    results: nextResults,
  };
}

function rows(): HTMLElement[] {
  return screen.getAllByTestId("trake-row");
}

describe("TrakeResultInspector", () => {
  it("renders exactly N event cells in fixed Event 1..N order", () => {
    render(<TrakeResultInspector response={response()} expectedEventCount={3} />);

    for (const row of rows()) {
      const cells = within(row).getAllByTestId("trake-event-cell");
      expect(cells).toHaveLength(3);
      expect(cells.map((cell) => cell.getAttribute("aria-label"))).toEqual([
        "EVENT 1",
        "EVENT 2",
        "EVENT 3",
      ]);
    }
  });

  it("opens the shared event modal with ASR and restores focus", async () => {
    const user = userEvent.setup();
    render(<TrakeResultInspector response={response()} expectedEventCount={3} />);
    const trigger = screen.getByRole("button", {
      name: "Open EVENT 2 details for L01_V001, frame 151",
    });

    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: /L01_V001.*151/ })).toHaveTextContent(
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
