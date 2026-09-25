import type { ObjectQueryTerm, SearchRequest, SearchResponse } from "../../api/types";

interface SearchInsightProps {
  response: SearchResponse;
  payload: SearchRequest | undefined;
  objectTerms: ObjectQueryTerm[];
  onPinObject: (term: ObjectQueryTerm) => void;
}

/** How the last search was interpreted: warnings, Gemini rewrite, weights and objects. */
export function SearchInsight({ response, payload, objectTerms, onPinObject }: SearchInsightProps) {
  const enhanced = payload?.enhance_query ? response.enhanced_query : null;
  const weights = payload?.enhance_query ? response.applied_weights : null;
  const autoObjects = response.query_type !== "TRAKE" ? (response.auto_object_query ?? []) : [];

  if (!response.warnings.length && !enhanced && !weights && autoObjects.length === 0) {
    return null;
  }

  return (
    <section className="search-insight" aria-label="Search insight">
      {response.warnings.length > 0 && (
        <ul className="search-insight__warnings" role="status">
          {response.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <div className="search-insight__row">
        {enhanced && (
          <div className="search-insight__item search-insight__item--grow">
            <small>Enhanced:</small>
            <p>{enhanced.replace(/^- /, "")}</p>
          </div>
        )}

        {weights && (
          <div className="search-insight__item">
            <small>Weights Applied:</small>
            <p className="search-insight__chips">
              <span>VIS: {weights.w_vis.toFixed(2)}</span>
              <span>ASR: {weights.w_asr.toFixed(2)}</span>
              {weights.w_obj !== undefined && <span>OBJ: {weights.w_obj.toFixed(2)}</span>}
            </p>
          </div>
        )}

        {autoObjects.length > 0 && (
          <div className="search-insight__item">
            <small>Auto objects:</small>
            <ul className="search-insight__chips" aria-label="Auto objects">
              {autoObjects.map((term) => {
                const pinned = objectTerms.some(
                  (manual) => manual.label.toLowerCase() === term.label.toLowerCase(),
                );
                return (
                  <li key={term.label}>
                    <span>
                      {term.label} ≥{term.min_count}
                    </span>
                    <button
                      type="button"
                      aria-label={`Pin ${term.label}`}
                      title="Giữ object này trong query object"
                      disabled={pinned || objectTerms.length >= 10}
                      onClick={() => onPinObject(term)}
                    >
                      {pinned ? "✓" : "+"}
                    </button>
                  </li>
                );
              })}
            </ul>
            {!payload?.search_sources.object && (
              <small className="search-insight__note">
                Bật nguồn Object để áp dụng các object này.
              </small>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
