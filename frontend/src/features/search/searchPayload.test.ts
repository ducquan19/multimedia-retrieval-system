import { describe, expect, it } from "vitest";

import type { PublicConfig } from "../../api/types";
import { matchesProgram, programOf, programOptions } from "./programFilter";
import {
  buildSearchRequest,
  effectiveSources,
  formFromRequest,
  type SearchFormState,
} from "./searchPayload";
import { EMPTY_TRAFFIC_FILTERS } from "./TrafficFilterPanel";

const config: PublicConfig = {
  min_top_k: 1,
  max_top_k: 500,
  default_top_k: 100,
  max_trake_events: 10,
  max_query_length: 20,
  max_answer_length: 100,
};

function form(overrides: Partial<SearchFormState> = {}): SearchFormState {
  return {
    activeType: "KIS",
    topK: "100",
    enhanceQuery: false,
    useReranking: false,
    sources: { image: true, asr: false, object: false },
    modelChoices: ["siglip"],
    objectTerms: [],
    kisQuery: "  a red car  ",
    queryUnderstanding: false,
    kisPlan: null,
    includeTraffic: false,
    trafficQuery: "",
    trafficFilters: EMPTY_TRAFFIC_FILTERS,
    trakeMainQuery: "",
    eventQueries: ["", "", ""],
    eventCount: 3,
    ...overrides,
  };
}

describe("buildSearchRequest", () => {
  it("builds a trimmed KIS request", () => {
    const { payload, errors } = buildSearchRequest(form(), config);

    expect(errors).toEqual([]);
    expect(payload).toEqual({
      query_type: "KIS",
      query: "a red car",
      include_traffic: false,
      top_k: 100,
      enhance_query: false,
      use_reranking: false,
      search_sources: { image: true, asr: false, object: false },
      model_choices: ["siglip"],
    });
  });

  it("reports every invalid field at once", () => {
    const { errors } = buildSearchRequest(
      form({
        topK: "501",
        kisQuery: " ",
        modelChoices: [],
        sources: { image: false, asr: false, object: false },
      }),
      config,
    );

    expect(errors).toEqual([
      "Top-K phải là số nguyên từ 1 đến 500.",
      "Chọn ít nhất một nguồn tìm kiếm.",
      "Chọn ít nhất một model.",
      "Truy vấn KIS không được để trống.",
    ]);
  });

  it("requires objects unless Enhance query picks them", () => {
    const sources = { image: true, asr: false, object: true };

    expect(buildSearchRequest(form({ sources }), config).errors).toEqual([
      "Thêm ít nhất một object hoặc bật Enhance query để tự chọn object.",
    ]);
    expect(buildSearchRequest(form({ sources, enhanceQuery: true }), config).errors).toEqual([]);
    const withObjects = buildSearchRequest(
      form({ sources, objectTerms: [{ label: "Car", min_count: 2 }] }),
      config,
    );
    expect(withObjects.payload).toMatchObject({ object_query: [{ label: "Car", min_count: 2 }] });
  });

  it("never sends ASR for TRAFFIC and checks the clock range", () => {
    const { payload, errors } = buildSearchRequest(
      form({
        activeType: "TRAFFIC",
        trafficQuery: "xe buýt",
        sources: { image: true, asr: true, object: false },
        trafficFilters: { ...EMPTY_TRAFFIC_FILTERS, clock_from: "18:00", clock_to: "07:00" },
      }),
      config,
    );

    expect(payload.search_sources).toEqual({ image: true, asr: false, object: false });
    expect(errors).toEqual(["Giờ bắt đầu phải trước giờ kết thúc."]);
  });

  it("numbers TRAKE events and validates only the visible ones", () => {
    const { payload, errors } = buildSearchRequest(
      form({
        activeType: "TRAKE",
        trakeMainQuery: " ",
        eventQueries: [" jump ", "fly", "this one is hidden and far too long"],
        eventCount: 2,
      }),
      config,
    );

    expect(errors).toEqual([]);
    expect(payload).toMatchObject({
      query_type: "TRAKE",
      main_query: undefined,
      events: [
        { event_index: 1, query: "jump" },
        { event_index: 2, query: "fly" },
      ],
    });
  });

  it("requires a plan when query understanding is on and disables enhance", () => {
    const { payload, errors } = buildSearchRequest(
      form({ queryUnderstanding: true, enhanceQuery: true }),
      config,
    );

    expect(errors).toEqual(["Hãy tạo và kiểm tra query plan trước khi tìm kiếm."]);
    expect(payload.enhance_query).toBe(false);
  });
});

describe("effectiveSources", () => {
  it("keeps the sources of every tab except TRAFFIC", () => {
    const sources = { image: false, asr: true, object: false };

    expect(effectiveSources("KIS", sources)).toBe(sources);
    expect(effectiveSources("TRAFFIC", sources).asr).toBe(false);
  });
});

describe("program filter", () => {
  it("groups batch 1 and batch 2 videos of the same programme", () => {
    expect(programOf("L21_V001")).toBe("NEWS");
    expect(programOf("M01_V010")).toBe("NEWS");
    expect(programOf("S01-V001")).toBe("CYCLING");
    expect(programOf("N001-V001")).toBe("TRAFFIC");
    expect(programOf("L27_V003")).toBe("L27");
    expect(matchesProgram("M02_V001", "NEWS")).toBe(true);
    expect(matchesProgram("M02_V001", "ALL")).toBe(true);
    expect(matchesProgram("M02_V001", "CYCLING")).toBe(false);
  });

  it("counts results per programme and keeps the selected one listed", () => {
    expect(programOptions(["L21_V001", "M01_V001", "L26_V002"], "CYCLING")).toEqual([
      { key: "CYCLING", label: "Đua xe đạp (0)" },
      { key: "L26", label: "Món ngon mỗi ngày (1)" },
      { key: "NEWS", label: "Tin tức (2)" },
    ]);
  });
});

describe("formFromRequest", () => {
  it.each([
    form({
      kisQuery: "người đàn ông áo đỏ",
      topK: "25",
      enhanceQuery: true,
      includeTraffic: true,
      sources: { image: true, asr: true, object: true },
      objectTerms: [{ label: "Car", min_count: 2 }],
      modelChoices: ["siglip", "beit3"],
    }),
    form({
      activeType: "TRAFFIC",
      trafficQuery: "xe buýt",
      trafficFilters: { ...EMPTY_TRAFFIC_FILTERS, dates: ["2026-06-07"], clock_from: "07:00" },
    }),
    form({
      activeType: "TRAKE",
      trakeMainQuery: "nhảy cao",
      eventQueries: ["giậm nhảy", "bay qua xà", "tiếp đất"],
      eventCount: 3,
      useReranking: true,
    }),
  ])("rebuilds the form of a $activeType request so it yields the same request", (original) => {
    const { payload } = buildSearchRequest(original, config);
    // Start from a form with other values everywhere, as when restoring from the history.
    const restored = { ...form({ topK: "7", kisQuery: "other" }), ...formFromRequest(payload) };

    expect(buildSearchRequest(restored, config).payload).toEqual(payload);
  });

  it("restores a KIS query plan with query understanding on", () => {
    const plan = {
      search_mode: "single_anchor" as const,
      events: [
        {
          event_index: 1,
          source_span_vi: "a",
          visual_query_en: "a",
          asr_query_vi: null,
          importance: "anchor" as const,
          confidence: 1,
          inferred: false,
        },
      ],
      warnings: [],
      planner_model: "gemini-3.5-flash-lite",
    };
    const { payload } = buildSearchRequest(
      form({ queryUnderstanding: true, kisPlan: plan }),
      config,
    );

    expect(formFromRequest(payload)).toMatchObject({ queryUnderstanding: true, kisPlan: plan });
  });
});
