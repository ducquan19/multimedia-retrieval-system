import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    model_choices: ["siglip", "beit3"],
    applied_weights: null,
    warnings: [],
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
  it("renders essential metadata and a consistently formatted score", () => {
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    const firstCard = cardAt(0);
    expect(firstCard).toHaveTextContent("L01_V001");
    expect(firstCard).toHaveTextContent("505");
    expect(firstCard).not.toHaveTextContent("Frame 505");
    expect(firstCard).toHaveTextContent("0.9821");
  });

  it("opens an accessible modal with ASR, OCR and objects, then restores focus", async () => {
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    const trigger = screen.getByRole("button", {
      name: "Open details for L01_V001, frame 505",
    });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: /L01_V001.*505/ });
    expect(dialog).not.toHaveTextContent("Keyframe detail");
    expect(dialog).not.toHaveTextContent("Segment");
    expect(dialog).not.toHaveTextContent("Similarity");
    expect(dialog).toHaveTextContent("Một người đang mở laptop trên bàn.");
    expect(dialog).toHaveTextContent("AIC 2026");
    expect(dialog).toHaveTextContent("laptop");
    expect(screen.getByRole("button", { name: "Close keyframe detail" })).toHaveFocus();
    await user.tab();
    const copyButton = screen.getByRole("button", { name: "Copy video ID and frame" });
    expect(copyButton).toHaveFocus();
    await user.click(copyButton);
    expect(await navigator.clipboard.readText()).toBe("L01_V001\t505");
    expect(copyButton).toHaveTextContent("Copied");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
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

  it("keeps the VQA answer in the current result session", async () => {
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("VQA")} maxAnswerLength={4_000} />);

    const answer = screen.getByLabelText("VQA Answer");
    await user.type(answer, "edited answer A");

    expect(screen.getByLabelText("VQA Answer")).toHaveValue("edited answer A");
  });

  it("hides manual move controls while retaining the original result order", () => {
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    expect(screen.queryByRole("button", { name: "Move up" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move down" })).not.toBeInTheDocument();
    expect(cardVideoOrder()).toEqual(["L01_V001", "L02_V002", "L03_V003"]);
  });

  it("shows a stable placeholder when a keyframe image fails", () => {
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    fireEvent.error(screen.getByAltText("Keyframe 505 from L01_V001"));

    expect(screen.getByText("Image unavailable")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Keyframe 505 from L01_V001" })).toBeInTheDocument();
  });

  it("groups candidates by video when requested", async () => {
    const user = userEvent.setup();
    const groupedResults = [
      results[0]!,
      results[1]!,
      { ...results[2]!, video_id: "L01_V001", similarity_score: 0.99 },
    ];
    render(
      <SingleResultInspector
        response={response("KIS", groupedResults)}
        maxAnswerLength={4_000}
      />,
    );

    expect(screen.queryByRole("heading", { name: "Results" })).not.toBeInTheDocument();
    expect(screen.queryByText("Editable result order")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Sort grouped results" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Group by video" }));

    const groups = screen.getAllByTestId("video-group");
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent("L01_V001");
    expect(groups[0]).toHaveTextContent("2 results");
    expect(groups[1]).toHaveTextContent("L02_V002");
    expect(within(groups[0]!).getAllByTestId("result-card")[0]).toHaveTextContent("1240");

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Sort grouped results" }),
      "time",
    );

    expect(within(groups[0]!).getAllByTestId("result-card")[0]).toHaveTextContent("505");
    expect(screen.queryByRole("button", { name: "Reset order" })).not.toBeInTheDocument();
  });

  it("initializes fresh order and answers for a new query response", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <SingleResultInspector response={response("VQA")} maxAnswerLength={4_000} />,
    );

    await user.type(screen.getByLabelText("VQA Answer"), "temporary answer");

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
    expect(screen.getByLabelText("VQA Answer")).toHaveValue("");
  });
});
