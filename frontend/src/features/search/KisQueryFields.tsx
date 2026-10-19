import { friendlySearchError } from "../../api/client";
import type { KISQueryPlan, KISQueryPlanEvent } from "../../api/types";
import { AutoGrowTextarea } from "../../shared/AutoGrowTextarea";
import { submitOnEnter } from "./submitOnEnter";
import type { SearchForm } from "./useSearchForm";

interface KisQueryFieldsProps {
  form: SearchForm;
  maxQueryLength: number;
}

/** The KIS query and, with Query Understanding on, the editable plan Gemini returns. */
export function KisQueryFields({ form, maxQueryLength }: KisQueryFieldsProps) {
  const { kisQuery, queryUnderstanding, kisPlan } = form.state;
  const { planMutation } = form;

  return (
    <>
      <label className="field" htmlFor="kis-query">
        <span className="field__label">Truy vấn KIS</span>
        <AutoGrowTextarea
          id="kis-query"
          className="field__query"
          value={kisQuery}
          maxLength={maxQueryLength}
          onChange={(event) => form.changeKisQuery(event.target.value)}
          onKeyDown={submitOnEnter}
          aria-keyshortcuts="Enter Shift+Enter"
          placeholder="Mô tả khoảnh khắc cần tìm, ví dụ: người đàn ông áo đỏ phát biểu trước micro"
          rows={3}
        />
      </label>

      <div className="plan">
        <div className="plan__head">
          <label className="switch-row" htmlFor="query-understanding">
            <span>
              Lập kế hoạch nhiều sự kiện
              <small id="query-understanding-hint">Gemini tách truy vấn thành các mốc để bạn sửa trước khi tìm</small>
            </span>
            <input
              id="query-understanding"
              type="checkbox"
              role="switch"
              aria-label="Lập kế hoạch nhiều sự kiện"
              aria-describedby="query-understanding-hint"
              checked={queryUnderstanding}
              onChange={(event) => form.toggleQueryUnderstanding(event.target.checked)}
            />
          </label>
          {queryUnderstanding && (
            <button
              type="button"
              className="button button--quiet"
              onClick={form.understandKisQuery}
              disabled={planMutation.isPending}
            >
              {planMutation.isPending ? "Đang phân tích…" : "Phân tích truy vấn"}
            </button>
          )}
        </div>

        {queryUnderstanding && planMutation.isError && (
          <p className="notice notice--error" role="alert">
            {friendlySearchError(planMutation.error)}
          </p>
        )}

        {queryUnderstanding && kisPlan && <KisPlanEditor form={form} plan={kisPlan} />}
      </div>
    </>
  );
}

function KisPlanEditor({ form, plan }: { form: SearchForm; plan: KISQueryPlan }) {
  return (
    <section className="plan__body" aria-label="Kế hoạch truy vấn KIS">
      <label className="field field--inline" htmlFor="kis-search-mode">
        <span className="field__label">Chiến lược</span>
        <select
          id="kis-search-mode"
          value={plan.search_mode}
          onChange={(event) =>
            form.setPlanSearchMode(event.target.value as KISQueryPlan["search_mode"])
          }
        >
          <option value="single_anchor">Một mốc chính</option>
          <option value="multi_anchor">Nhiều mốc, không theo thứ tự</option>
          <option value="temporal_sequence">Theo thứ tự thời gian</option>
        </select>
      </label>

      <ol className="plan__events">
        {plan.events.map((planEvent, index) => (
          <li className="plan-event" key={planEvent.event_index}>
            <header className="plan-event__head">
              <span className="sequence-mark" aria-hidden="true">
                E{planEvent.event_index}
              </span>
              <strong>EVENT {planEvent.event_index}</strong>
              <span className="plan-event__confidence">
                {Math.round(planEvent.confidence * 100)}% tin cậy
              </span>
              <button
                type="button"
                className="button button--text"
                onClick={() => form.removePlanEvent(index)}
                disabled={plan.events.length === 1}
                aria-label={`Xoá EVENT ${planEvent.event_index}`}
              >
                Xoá
              </button>
            </header>
            <p className="plan-event__source">{planEvent.source_span_vi}</p>
            <label className="field">
              <span className="field__label">Hình ảnh (tiếng Anh)</span>
              <AutoGrowTextarea
                aria-label={`Truy vấn hình ảnh EVENT ${planEvent.event_index}`}
                value={planEvent.visual_query_en ?? ""}
                onChange={(event) =>
                  form.updatePlanEvent(index, { visual_query_en: event.target.value || null })
                }
                rows={2}
              />
            </label>
            <label className="field">
              <span className="field__label">Lời thoại ASR (tiếng Việt)</span>
              <AutoGrowTextarea
                aria-label={`Truy vấn ASR EVENT ${planEvent.event_index}`}
                value={planEvent.asr_query_vi ?? ""}
                onChange={(event) =>
                  form.updatePlanEvent(index, { asr_query_vi: event.target.value || null })
                }
                rows={2}
              />
            </label>
            <label className="field field--inline">
              <span className="field__label">Vai trò</span>
              <select
                aria-label={`Vai trò EVENT ${planEvent.event_index}`}
                value={planEvent.importance}
                onChange={(event) =>
                  form.updatePlanEvent(index, {
                    importance: event.target.value as KISQueryPlanEvent["importance"],
                  })
                }
              >
                <option value="anchor">Mốc chính</option>
                <option value="supporting">Hỗ trợ</option>
                <option value="context">Bối cảnh</option>
              </select>
            </label>
            {planEvent.inferred && (
              <p className="notice notice--warning">
                Có suy luận ngoài câu gốc. Kiểm tra trước khi tìm.
              </p>
            )}
          </li>
        ))}
      </ol>

      {plan.warnings.map((warning) => (
        <p className="notice notice--warning" key={warning}>
          {warning}
        </p>
      ))}
    </section>
  );
}
