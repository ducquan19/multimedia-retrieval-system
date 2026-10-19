import { describe, expect, it } from "vitest";

import type { SingleSearchResult } from "../../api/types";
import { shownResults } from "./resultBrowsing";

function result(id: string, video: string, segment: string, frame = 0): SingleSearchResult {
  return {
    result_id: id,
    rank: 0,
    video_id: video,
    frame_id: frame,
    keyframe_url: `/media/${id}.jpg`,
    image_path: `${id}.jpg`,
    segment_id: segment,
    asr_text: "",
    objects: [],
    similarity_score: 0,
    answer: "",
    time_ms: null,
    camera_name: null,
    clock_time: null,
    weather: null,
  };
}

const RESULTS = [
  result("a", "L01_V001", "S1"),
  result("b", "L01_V001", "S1"),
  result("c", "L02_V001", "S1"),
  result("d", "L01_V001", "S2"),
  result("e", "L01_V001", "S1"),
];

const none = new Set<string>();

describe("shownResults", () => {
  it("keeps every result with its rank when nothing is collapsed or hidden", () => {
    const shown = shownResults(RESULTS, { collapse: false, hiddenVideos: none });

    expect(shown.map(({ result: r, rank, folded }) => [r.result_id, rank, folded])).toEqual([
      ["a", 1, 0],
      ["b", 2, 0],
      ["c", 3, 0],
      ["d", 4, 0],
      ["e", 5, 0],
    ]);
  });

  it("keeps the best result of each shot and counts the others", () => {
    const shown = shownResults(RESULTS, { collapse: true, hiddenVideos: none });

    // Shot S1 of another video is another shot.
    expect(shown.map(({ result: r, rank, folded }) => [r.result_id, rank, folded])).toEqual([
      ["a", 1, 2],
      ["c", 3, 0],
      ["d", 4, 0],
    ]);
  });

  it("groups frames without a shot into ten-second windows", () => {
    // 0 s, 5 s and 12 s at 25 fps
    const noShot = [
      result("a", "M01_V001", "", 0),
      result("b", "M01_V001", "", 125),
      result("c", "M01_V001", "", 300),
    ];

    const shown = shownResults(noShot, { collapse: true, hiddenVideos: none });

    expect(shown.map(({ result: r, folded }) => [r.result_id, folded])).toEqual([
      ["a", 1],
      ["c", 0],
    ]);
  });

  it("drops the hidden videos", () => {
    const shown = shownResults(RESULTS, { collapse: false, hiddenVideos: new Set(["L01_V001"]) });

    expect(shown.map(({ result: r, rank }) => [r.result_id, rank])).toEqual([["c", 3]]);
  });
});
