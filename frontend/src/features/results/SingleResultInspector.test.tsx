import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  KISSearchResponse,
  SingleSearchResult,
  VQASearchResponse,
} from "../../api/types";
import { renderWithQuery as render } from "../../test/renderWithQuery";
import { SingleResultInspector } from "./SingleResultInspector";

// What the backend returns besides the fields these tests vary.
const resultDefaults = {
  image_path: "keyframes/frame.jpg",
  time_ms: null,
  camera_name: null,
  clock_time: null,
  weather: null,
} satisfies Partial<SingleSearchResult>;

const results: SingleSearchResult[] = [
  {
    ...resultDefaults,
    result_id: "result-a",
    rank: 1,
    video_id: "L01_V001",
    frame_id: 505,
    keyframe_url: "/media/keyframes/a.jpg",
    segment_id: "segment-a",
    asr_text: "Một người đang mở laptop trên bàn.",
    objects: [{ label: "laptop", score: 0.97 }],
    similarity_score: 0.9821,
    answer: "answer A",
  },
  {
    ...resultDefaults,
    result_id: "result-b",
    rank: 2,
    video_id: "L02_V002",
    frame_id: 910,
    keyframe_url: "/media/keyframes/b.jpg",
    segment_id: "segment-b",
    asr_text: "Diễn giả bắt đầu phần trình bày.",
    objects: [],
    similarity_score: 0.9012,
    answer: "answer B",
  },
  {
    ...resultDefaults,
    result_id: "result-c",
    rank: 3,
    video_id: "L03_V003",
    frame_id: 1240,
    keyframe_url: "/media/keyframes/c.jpg",
    segment_id: "segment-c",
    asr_text: "Khán giả đang vỗ tay.",
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
    auto_object_query: [],
    results: nextResults,
  };
  return queryType === "KIS"
    ? ({ ...base, query_type: "KIS", query_plan: null } satisfies KISSearchResponse)
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

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function stubVideoApi() {
  const fetchMock = vi.fn((input: RequestInfo | URL) =>
    Promise.resolve(
      String(input).includes("/keyframes?")
        ? jsonResponse({
            video_id: "L01_V001",
            center_index: 1,
            keyframes: [400, 505, 610].map((frameId) => ({
              frame_id: frameId,
              keyframe_url: `/media/keyframes/L01_V001/${frameId}.jpg`,
              segment_id: "",
              asr_text: `ASR at ${frameId}`,
              objects: [],
            })),
          })
        : jsonResponse({
            video_id: "L01_V001",
            url: "/media/videos/L01_V001.mp4",
            source: "local",
            fps: 25,
          }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
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

  it("opens an accessible modal with ASR and objects, then restores focus", async () => {
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    const trigger = screen.getByRole("button", {
      name: "Mở chi tiết L01_V001, frame 505",
    });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: /L01_V001.*505/ });
    expect(dialog).not.toHaveTextContent("Keyframe detail");
    expect(dialog).not.toHaveTextContent("Segment");
    expect(dialog).not.toHaveTextContent("Similarity");
    expect(dialog).toHaveTextContent("Một người đang mở laptop trên bàn.");
    expect(dialog).toHaveTextContent("laptop");
    expect(screen.getByRole("button", { name: "Đóng" })).toHaveFocus();
    await user.tab();
    const copyButton = screen.getByRole("button", { name: "Sao chép mã video và frame" });
    expect(copyButton).toHaveFocus();
    await user.click(copyButton);
    expect(await navigator.clipboard.readText()).toBe("L01_V001\t505");
    expect(copyButton).toHaveTextContent("Đã chép");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("keeps the VQA answer in the current result session", async () => {
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("VQA")} maxAnswerLength={4_000} />);

    const answer = screen.getByLabelText("Câu trả lời VQA");
    await user.type(answer, "edited answer A");

    expect(screen.getByLabelText("Câu trả lời VQA")).toHaveValue("edited answer A");
  });

  it("moves to a neighbouring keyframe from the strip and with the arrow keys", async () => {
    stubVideoApi();
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    await user.click(
      screen.getByRole("button", { name: "Mở chi tiết L01_V001, frame 505" }),
    );
    const strip = await screen.findByRole("region", { name: "Temporal context" });
    expect(
      await within(strip).findByRole("button", { name: "Keyframe 505" }),
    ).toHaveAttribute("aria-current", "true");

    await user.click(within(strip).getByRole("button", { name: "Keyframe 610" }));
    const dialog = screen.getByRole("dialog");
    const title = within(dialog).getByRole("heading", { level: 2 });
    expect(title).toHaveTextContent("610");
    expect(within(dialog).getByText("ASR at 610")).toBeInTheDocument();

    await user.keyboard("{ArrowLeft}");
    expect(title).toHaveTextContent("505");
  });

  it("plays the video from the keyframe timestamp", async () => {
    const fetchMock = stubVideoApi();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    await user.click(
      screen.getByRole("button", { name: "Mở chi tiết L01_V001, frame 505" }),
    );
    await user.click(screen.getByRole("button", { name: "Phát video" }));

    const video = await screen.findByText("Trình duyệt không phát được video này.");
    const videoElement = video.closest("video");
    if (!(videoElement instanceof HTMLVideoElement)) throw new Error("Expected video player");
    Object.defineProperty(videoElement, "duration", { configurable: true, value: 100 });
    fireEvent.loadedMetadata(videoElement);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/videos/L01_V001/source",
      expect.objectContaining({ headers: expect.objectContaining({ Accept: "application/json" }) }),
    );
    expect(videoElement.currentTime).toBeCloseTo(505 / 25);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Xem keyframe" })).toBeInTheDocument();

    const frameInput = screen.getByRole("spinbutton", { name: "Frame hiện tại" });
    expect(frameInput).toHaveValue(505);
    videoElement.currentTime = 22;
    fireEvent.timeUpdate(videoElement);
    expect(frameInput).toHaveValue(550);
    await user.click(screen.getByRole("button", { name: "Sao chép frame hiện tại" }));
    expect(await navigator.clipboard.readText()).toBe("550");
    expect(screen.getByRole("button", { name: "Sao chép frame hiện tại" })).toHaveTextContent(
      "Đã chép",
    );

    await user.click(screen.getByRole("button", { name: "Frame sau" }));
    expect(frameInput).toHaveValue(551);
    expect(videoElement.currentTime).toBeCloseTo(551 / 25);
    await user.click(screen.getByRole("button", { name: "Frame trước" }));
    expect(frameInput).toHaveValue(550);
    expect(videoElement.currentTime).toBeCloseTo(550 / 25);

    videoElement.currentTime = 40;
    await user.click(screen.getByRole("button", { name: "Về keyframe" }));
    expect(videoElement.currentTime).toBeCloseTo(505 / 25);
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Xem keyframe" }));
    expect(screen.queryByRole("spinbutton", { name: "Frame hiện tại" })).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("dialog")).getByAltText("Keyframe 505 của L01_V001"),
    ).toBeInTheDocument();
  });

  it("hides manual move controls while retaining the original result order", () => {
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    expect(screen.queryByRole("button", { name: "Move up" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move down" })).not.toBeInTheDocument();
    expect(cardVideoOrder()).toEqual(["L01_V001", "L02_V002", "L03_V003"]);
  });

  it("shows a stable placeholder when a keyframe image fails", () => {
    render(<SingleResultInspector response={response("KIS")} maxAnswerLength={4_000} />);

    fireEvent.error(screen.getByAltText("Keyframe 505 của L01_V001"));

    expect(screen.getByText("Không có ảnh")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Keyframe 505 của L01_V001" })).toBeInTheDocument();
  });

  it("groups candidates by video when requested", async () => {
    const groupedResults = [
      results[0]!,
      results[1]!,
      { ...results[2]!, video_id: "L01_V001", similarity_score: 0.99 },
    ];
    const { rerender } = render(
      <SingleResultInspector
        response={response("KIS", groupedResults)}
        maxAnswerLength={4_000}
        groupByVideo
        groupSort="score"
      />,
    );

    expect(screen.queryByRole("heading", { name: "Results" })).not.toBeInTheDocument();
    expect(screen.queryByText("Editable result order")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Sắp xếp trong nhóm" })).not.toBeInTheDocument();

    const groups = screen.getAllByTestId("video-group");
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent("L01_V001");
    expect(groups[0]).toHaveTextContent("2 kết quả");
    expect(groups[1]).toHaveTextContent("L02_V002");
    expect(within(groups[0]!).getAllByTestId("result-card")[0]).toHaveTextContent("1240");

    rerender(
      <SingleResultInspector
        response={response("KIS", groupedResults)}
        maxAnswerLength={4_000}
        groupByVideo
        groupSort="time"
      />,
    );

    const timeSortedGroups = screen.getAllByTestId("video-group");
    expect(within(timeSortedGroups[0]!).getAllByTestId("result-card")[0]).toHaveTextContent("505");
    expect(screen.queryByRole("button", { name: "Reset order" })).not.toBeInTheDocument();
  });

  it("initializes fresh order and answers for a new query response", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <SingleResultInspector response={response("VQA")} maxAnswerLength={4_000} />,
    );

    await user.type(screen.getByLabelText("Câu trả lời VQA"), "temporary answer");

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
    expect(screen.getByLabelText("Câu trả lời VQA")).toHaveValue("");
  });
});
