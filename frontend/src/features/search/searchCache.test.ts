import { describe, expect, it } from "vitest";

import type { KISSearchRequest, SearchResponse } from "../../api/types";
import { requestKey, SearchResultCache } from "./searchCache";

function kis(query: string, overrides: Partial<KISSearchRequest> = {}): KISSearchRequest {
  return {
    query_type: "KIS",
    query,
    top_k: 100,
    enhance_query: false,
    use_reranking: false,
    search_sources: { image: true, asr: false, object: false },
    model_choices: ["siglip"],
    ...overrides,
  };
}

const response = { query_type: "KIS", results: [] } as unknown as SearchResponse;

describe("requestKey", () => {
  it("ignores the order of object keys but not of list items", () => {
    const a = kis("x");
    const reordered = {
      model_choices: ["siglip"],
      search_sources: { object: false, asr: false, image: true },
      use_reranking: false,
      enhance_query: false,
      top_k: 100,
      query: "x",
      query_type: "KIS",
    } as KISSearchRequest;

    expect(requestKey(reordered)).toBe(requestKey(a));
    expect(requestKey(kis("x", { model_choices: ["siglip", "beit3"] }))).not.toBe(
      requestKey(kis("x", { model_choices: ["beit3", "siglip"] })),
    );
  });

  it("tells requests with different options apart", () => {
    expect(requestKey(kis("x"))).not.toBe(requestKey(kis("x", { top_k: 50 })));
    expect(requestKey(kis("x"))).not.toBe(
      requestKey(kis("x", { search_sources: { image: true, asr: true, object: false } })),
    );
  });
});

describe("SearchResultCache", () => {
  it("returns a saved result for an equal request", () => {
    const cache = new SearchResultCache();
    cache.put({ payload: kis("x"), response, at: 1 });

    expect(cache.has(kis("x"))).toBe(true);
    expect(cache.get(kis("x"))?.at).toBe(1);
    expect(cache.get(kis("y"))).toBeUndefined();
  });

  it("drops the least recently used result when full", () => {
    const cache = new SearchResultCache(2);
    cache.put({ payload: kis("a"), response, at: 1 });
    cache.put({ payload: kis("b"), response, at: 2 });
    cache.get(kis("a")); // "a" is now more recent than "b"
    cache.put({ payload: kis("c"), response, at: 3 });

    expect(cache.has(kis("a"))).toBe(true);
    expect(cache.has(kis("b"))).toBe(false);
    expect(cache.has(kis("c"))).toBe(true);
  });

  it("replaces the saved result when the same request runs again", () => {
    const cache = new SearchResultCache();
    cache.put({ payload: kis("x"), response, at: 1 });
    cache.put({ payload: kis("x"), response, at: 2 });

    expect(cache.get(kis("x"))?.at).toBe(2);
  });
});
