import { useState } from "react";

import type { ObjectQueryTerm, SearchRequest, SearchResponse } from "../../api/types";

const OPEN_STORAGE_KEY = "aic-search-insight-open";

function readOpen(): boolean {
  try {
    return window.localStorage.getItem(OPEN_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

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
  // Collapsed by default so the keyframe grid keeps the space; the choice is remembered.
  const [open, setOpen] = useState(readOpen);
  const hasDetails = Boolean(enhanced || weights || autoObjects.length > 0);

  const toggle = () => {
    setOpen((current) => {
      try {
        window.localStorage.setItem(OPEN_STORAGE_KEY, String(!current));
      } catch {
        // The toggle still applies for this session.
      }
      return !current;
    });
  };

  const weightChips = weights && (
    <>
      <span>VIS: {weights.w_vis.toFixed(2)}</span>
      <span>ASR: {weights.w_asr.toFixed(2)}</span>
      {weights.w_obj !== undefined && <span>OBJ: {weights.w_obj.toFixed(2)}</span>}
    </>
  );

  if (!response.warnings.length && !enhanced && !weights && autoObjects.length === 0) {
    return null;
  }

  return (
    <section
      className={`search-insight${open ? "" : " search-insight--collapsed"}`}
      aria-label="Search insight"
    >
      {response.warnings.length > 0 && (
        <ul className="search-insight__warnings" role="status">
          {response.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      {hasDetails && !open && (
        <button
          type="button"
          className="search-insight__bar"
          aria-expanded={false}
          aria-label="Mở rộng search insight"
          onClick={toggle}
        >
          <span className="search-insight__caret" aria-hidden="true">▸</span>
          {enhanced && (
            <span className="search-insight__summary" title={enhanced.replace(/^- /, "")}>
              <small>Enhanced:</small> {enhanced.replace(/^- /, "")}
            </span>
          )}
          {weights && <span className="search-insight__chips">{weightChips}</span>}
          {autoObjects.length > 0 && (
            <span className="search-insight__count">{autoObjects.length} auto objects</span>
          )}
        </button>
      )}

      {hasDetails && open && (
        <div className="search-insight__row">
          <button
            type="button"
            className="search-insight__collapse"
            aria-expanded={true}
            aria-label="Thu gọn search insight"
            title="Thu gọn"
            onClick={toggle}
          >
            ▾
          </button>
          {enhanced && (
            <div className="search-insight__item search-insight__item--grow">
              <small>Enhanced:</small>
              <p>{enhanced.replace(/^- /, "")}</p>
            </div>
          )}

          {weights && (
            <div className="search-insight__item">
              <small>Weights Applied:</small>
              <p className="search-insight__chips">{weightChips}</p>
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
      )}
    </section>
  );
}
