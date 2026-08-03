import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type {
  KISSearchResponse,
  SingleSearchResult,
  VQASearchResponse,
} from "../../api/types";
import { SingleResultInspector } from "./SingleResultInspector";
import { createResultEditorState, resultEditorReducer } from "./resultState";

const results: SingleSearchResult[] = [
  {
    result_id: "result-a",
    rank: 1,
    video_id: "L01_V001",
    frame_id: 505,
    keyframe_url: "/media/keyframes/a.jpg",
    segment_id: "segment-a",
    asr_text: "Một người đang mở laptop trên bàn.",
    ocr_text: "AIC 2026",
    objects: [{ label: "laptop", score: 0.97 }],
    similarity_score: 0.9821,
    answer: "answer A",
  },
  {
    result_id: "result-b",
    rank: 2,
    video_id: "L02_V002",
    frame_id: 910,
    keyframe_url: "/media/keyframes/b.jpg",
    segment_id: "segment-b",
    asr_text: "Diễn giả bắt đầu phần trình bày.",
    ocr_text: "",
    objects: [],
    similarity_score: 0.9012,
    answer: "answer B",
  },
  {
    result_id: "result-c",
    rank: 3,
    video_id: "L03_V003",
    frame_id: 1240,
    keyframe_url: "/media/keyframes/c.jpg",
    segment_id: "segment-c",
    asr_text: "Khán giả đang vỗ tay.",
    ocr_text: "",
    objects: [],
    similarity_score: 0.85,
    answer: "answer C",
  },
];

function response(queryType: "KIS" | "VQA", nextResults = results) {
  const base = {
    original_query: "query",
    enhanced_query: null,
    retrieval_mode: "mock" as const,
    results: nextResults,
  };
  return queryType === "KIS"
    ? ({ ...base, query_type: "KIS" } satisfies KISSearchResponse)
    : ({ ...base, query_type: "VQA" } satisfies VQASearchResponse);
}

function cardVideoOrder(): string[] {
  return screen.getAllByTestId("result-card").map((card) => {
    const videoId = within(card).getByText(/^L\d{2}_V\d{3}$/);
    return videoId.textContent ?? "";
  });
}

function cardAt(index: number): HTMLElement {
  const card = screen.getAllByTestId("result-card")[index];
  if (!card) throw new Error(`Expected result card at index ${index}`);
  return card;
}

describe("SingleResultInspector", () => {
  it("renders current rank, metadata and consistently formatted score", () => {
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    const firstCard = cardAt(0);
    expect(firstCard).toHaveTextContent("#1");
    expect(firstCard).toHaveTextContent("L01_V001");
    expect(firstCard).toHaveTextContent("Frame 505");
    expect(firstCard).toHaveTextContent("segment-a");
    expect(firstCard).toHaveTextContent("98.21%");
  });

  it("opens an accessible modal with ASR, OCR and objects, then restores focus", async () => {
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    const trigger = screen.getByRole("button", {
      name: "Open details for L01_V001, frame 505",
    });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "L01_V001" });
    expect(dialog).toHaveTextContent("Một người đang mở laptop trên bàn.");
    expect(dialog).toHaveTextContent("AIC 2026");
    expect(dialog).toHaveTextContent("laptop");
    expect(screen.getByRole("button", { name: "Close keyframe detail" })).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("moves cards with fallback buttons and updates current ranks", async () => {
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    await user.click(screen.getByRole("button", { name: "Move L02_V002 up" }));

    expect(cardVideoOrder()).toEqual(["L02_V002", "L01_V001", "L03_V003"]);
    expect(cardAt(0)).toHaveTextContent("#1");
    expect(cardAt(1)).toHaveTextContent("#2");
  });

  it("reorders IDs through the same reducer path used by drag end", () => {
    const initial = createResultEditorState(results);
    const moved = resultEditorReducer(initial, {
      type: "move",
      activeId: "result-c",
      overId: "result-a",
    });

    expect(moved.order).toEqual(["result-c", "result-a", "result-b"]);
  });

  it("keeps VQA answers attached to result_id after reorder", async () => {
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("VQA")} maxAnswerLength={4_000} />);

    const firstCard = cardAt(0);
    const answer = within(firstCard).getByLabelText("VQA answer");
    await user.clear(answer);
    await user.type(answer, "edited answer A");
    await user.click(within(firstCard).getByRole("button", { name: "Move L01_V001 down" }));

    expect(within(cardAt(1)).getByText("L01_V001")).toBeInTheDocument();
    expect(within(cardAt(1)).getByLabelText("VQA answer")).toHaveValue(
      "edited answer A",
    );
  });

  it("resets to the original API order", async () => {
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    await user.click(screen.getByRole("button", { name: "Move L02_V002 up" }));
    expect(cardVideoOrder()[0]).toBe("L02_V002");
    await user.click(screen.getByRole("button", { name: "Reset order" }));

    expect(cardVideoOrder()).toEqual(["L01_V001", "L02_V002", "L03_V003"]);
  });

  it("shows a stable placeholder when a keyframe image fails", () => {
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    fireEvent.error(screen.getByAltText("Keyframe 505 from L01_V001"));

    expect(screen.getByText("Image unavailable")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Keyframe 505 from L01_V001" })).toBeInTheDocument();
  });

  it("initializes fresh order and answers for a new query response", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <SingleResultInspector response={response("VQA")} maxAnswerLength={4_000} />,
    );

    await user.type(within(cardAt(0)).getByLabelText("VQA answer"), "!");
    await user.click(screen.getByRole("button", { name: "Move L02_V002 up" }));

    const sourceResult = results[2];
    if (!sourceResult) throw new Error("Expected source result");
    const freshResults: SingleSearchResult[] = [
      { ...sourceResult, result_id: "fresh-result", answer: "fresh answer", rank: 1 },
    ];
    rerender(
      <SingleResultInspector
        response={response("VQA", freshResults)}
        maxAnswerLength={4_000}
      />,
    );

    expect(cardVideoOrder()).toEqual(["L03_V003"]);
    expect(screen.getByLabelText("VQA answer")).toHaveValue("fresh answer");
  });
});
