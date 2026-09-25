import { describe, expect, it } from "vitest";

import { parseTrakeEvents } from "./trakeEventParser";

describe("parseTrakeEvents", () => {
  it("splits E1..En lines into events in order", () => {
    expect(
      parseTrakeEvents("E1: người đàn ông mở cửa\nE2: bước vào phòng\nE3: ngồi xuống ghế"),
    ).toEqual({
      mainQuery: "",
      events: ["người đàn ông mở cửa", "bước vào phòng", "ngồi xuống ghế"],
    });
  });

  it("accepts marker variants, keeps a preamble and joins continuation lines", () => {
    expect(
      parseTrakeEvents(
        "Buổi lễ khai giảng\r\n\r\ne1. học sinh xếp hàng\r\n  dưới sân trường\r\nEvent 2 - hiệu trưởng phát biểu\r\nE 3) đánh trống",
      ),
    ).toEqual({
      mainQuery: "Buổi lễ khai giảng",
      events: ["học sinh xếp hàng dưới sân trường", "hiệu trưởng phát biểu", "đánh trống"],
    });
  });

  it("places events by their number, leaving gaps empty", () => {
    expect(parseTrakeEvents("E2: sau\nE1: trước\nE4: cuối")?.events).toEqual([
      "trước",
      "sau",
      "",
      "cuối",
    ]);
  });

  it("returns null for text without event markers", () => {
    expect(parseTrakeEvents("một câu mô tả bình thường")).toBeNull();
    expect(parseTrakeEvents("Every day E3 camera")).toBeNull();
  });
});
