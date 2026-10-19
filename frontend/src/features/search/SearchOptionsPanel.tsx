import type { SearchSources } from "../../api/types";
import { ObjectQueryInput } from "./ObjectQueryInput";
import type { SearchForm } from "./useSearchForm";

const SOURCE_OPTIONS: { key: keyof SearchSources; label: string }[] = [
  { key: "image", label: "Ảnh" },
  { key: "asr", label: "ASR" },
  { key: "object", label: "Object" },
];

/** Sources, required objects, image models and the Gemini / BLIP-2 switches. */
export function SearchOptionsPanel({ form }: { form: SearchForm }) {
  const { activeType, sources, objectTerms, modelChoices, enhanceQuery, useReranking } =
    form.state;
  const { planned } = form;

  return (
    <>
      <div className="rail__section">
        <fieldset className="chip-group" disabled={planned}>
          <legend>Nguồn</legend>
          {SOURCE_OPTIONS.filter(({ key }) => !(activeType === "TRAFFIC" && key === "asr")).map(
            ({ key, label }) => (
              <label className="chip" key={key}>
                <input
                  type="checkbox"
                  checked={sources[key]}
                  onChange={(event) => form.toggleSource(key, event.target.checked)}
                />
                <span>{label}</span>
              </label>
            ),
          )}
        </fieldset>

        {sources.object && (
          <ObjectQueryInput
            terms={objectTerms}
            onChange={form.setObjectTerms}
            disabled={planned}
            autoObjects={enhanceQuery}
          />
        )}

        <fieldset className="chip-group">
          <legend>Model ảnh</legend>
          <label className="chip">
            <input
              type="checkbox"
              checked={modelChoices.includes("siglip")}
              onChange={(event) => form.toggleModel("siglip", event.target.checked)}
            />
            <span>SigLIP-2</span>
          </label>
          <label className="chip">
            <input
              type="checkbox"
              checked={modelChoices.includes("beit3")}
              onChange={(event) => form.toggleModel("beit3", event.target.checked)}
            />
            <span>BEiT-3</span>
          </label>
        </fieldset>
      </div>

      <div className="rail__section rail__switches">
        <label className="switch-row" htmlFor="enhance-query">
          <span>
            Enhance query
            <small id="enhance-query-hint">Gemini viết lại truy vấn, chọn object và trọng số từng nguồn</small>
          </span>
          <input
            id="enhance-query"
            type="checkbox"
            role="switch"
            aria-label="Enhance query"
            aria-describedby="enhance-query-hint"
            checked={enhanceQuery}
            disabled={planned}
            onChange={(event) => form.setEnhanceQuery(event.target.checked)}
          />
        </label>
        <label className="switch-row" htmlFor="use-reranking">
          <span>
            Rerank BLIP-2
            <small id="use-reranking-hint">Chấm lại các kết quả đầu, chậm hơn</small>
          </span>
          <input
            id="use-reranking"
            type="checkbox"
            role="switch"
            aria-label="Rerank BLIP-2"
            aria-describedby="use-reranking-hint"
            checked={useReranking}
            onChange={(event) => form.setUseReranking(event.target.checked)}
          />
        </label>
        {activeType === "KIS" && (
          <label className="switch-row" htmlFor="include-traffic">
            <span>Gồm video giao thông (N)</span>
            <input
              id="include-traffic"
              type="checkbox"
              role="switch"
              checked={form.state.includeTraffic}
              onChange={(event) => form.setIncludeTraffic(event.target.checked)}
            />
          </label>
        )}
      </div>
    </>
  );
}
