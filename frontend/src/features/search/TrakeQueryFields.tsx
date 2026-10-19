import { AutoGrowTextarea } from "../../shared/AutoGrowTextarea";
import { submitOnEnter } from "./submitOnEnter";
import type { SearchForm } from "./useSearchForm";

interface TrakeQueryFieldsProps {
  form: SearchForm;
  maxQueryLength: number;
  maxEvents: number;
}

/** The main TRAKE query and one query per EVENT; pasting "E1: … E2: …" fills them all. */
export function TrakeQueryFields({ form, maxQueryLength, maxEvents }: TrakeQueryFieldsProps) {
  const { trakeMainQuery, eventCount, eventQueries } = form.state;

  return (
    <>
      <label className="field" htmlFor="trake-main-query">
        <span className="field__label">Truy vấn chính</span>
        <AutoGrowTextarea
          id="trake-main-query"
          value={trakeMainQuery}
          maxLength={maxQueryLength}
          onChange={(event) => form.setTrakeMainQuery(event.target.value)}
          onKeyDown={submitOnEnter}
          onPaste={form.pasteTrakeEvents}
          aria-keyshortcuts="Enter Shift+Enter"
          placeholder={"Dán cả đề bài để tự tách EVENT:\nE1: …\nE2: …\nE3: …"}
          rows={3}
        />
      </label>

      <label className="field field--inline" htmlFor="event-count">
        <span className="field__label">Số EVENT</span>
        <select
          id="event-count"
          value={eventCount}
          onChange={(event) => form.changeEventCount(Number(event.target.value))}
        >
          {Array.from({ length: maxEvents }, (_, i) => i + 1).map((count) => (
            <option key={count} value={count}>
              {count}
            </option>
          ))}
        </select>
      </label>

      <ol className="trake-events">
        {eventQueries.slice(0, eventCount).map((query, index) => (
          <li key={index}>
            <label className="trake-event" htmlFor={`event-${index + 1}`}>
              <span className="sequence-mark" aria-hidden="true">
                E{index + 1}
              </span>
              <AutoGrowTextarea
                id={`event-${index + 1}`}
                aria-label={`EVENT ${index + 1}`}
                value={query}
                maxLength={maxQueryLength}
                onChange={(event) => form.updateEventQuery(index, event.target.value)}
                onKeyDown={submitOnEnter}
                onPaste={form.pasteTrakeEvents}
                aria-keyshortcuts="Enter Shift+Enter"
                placeholder={`Sự kiện ${index + 1}`}
                rows={1}
              />
            </label>
          </li>
        ))}
      </ol>
    </>
  );
}
