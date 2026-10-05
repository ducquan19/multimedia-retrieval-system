import { type KeyboardEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getObjectLabels } from "../../api/client";
import type { ObjectQueryTerm } from "../../api/types";

const MAX_OBJECT_TERMS = 10;
const MIN_COUNT_OPTIONS = Array.from({ length: 10 }, (_, i) => i + 1);

interface ObjectQueryInputProps {
  terms: ObjectQueryTerm[];
  onChange: (terms: ObjectQueryTerm[]) => void;
  disabled?: boolean;
  /** Enhance query is on, so Gemini adds detector objects on top of these terms. */
  autoObjects?: boolean;
}

export function ObjectQueryInput({
  terms,
  onChange,
  disabled = false,
  autoObjects = false,
}: ObjectQueryInputProps) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const labelsQuery = useQuery({
    queryKey: ["object-labels"],
    queryFn: ({ signal }) => getObjectLabels(signal),
    staleTime: Infinity,
    retry: false,
  });
  const labels = labelsQuery.data?.labels ?? [];
  const indexUnavailable = labelsQuery.data?.available === false;

  const addTerm = () => {
    const typed = draft.trim();
    if (!typed) return;
    const label =
      labels.find((candidate) => candidate.toLowerCase() === typed.toLowerCase()) ?? typed;
    if (labels.length > 0 && !labels.includes(label)) {
      setError(`Không có object "${typed}" trong index.`);
      return;
    }
    if (terms.some((term) => term.label.toLowerCase() === label.toLowerCase())) {
      setError(`"${label}" đã có trong danh sách.`);
      return;
    }
    if (terms.length >= MAX_OBJECT_TERMS) {
      setError(`Tối đa ${MAX_OBJECT_TERMS} object.`);
      return;
    }
    onChange([...terms, { label, min_count: 1 }]);
    setDraft("");
    setError(null);
  };

  const addOnEnter = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    // Enter adds an object instead of submitting the search form.
    event.preventDefault();
    addTerm();
  };

  const updateMinCount = (index: number, minCount: number) => {
    onChange(terms.map((term, i) => (i === index ? { ...term, min_count: minCount } : term)));
  };

  return (
    <div className="object-query">
      <div className="object-query__add">
        <input
          type="text"
          aria-label="Tên object"
          list="object-label-options"
          placeholder="Person, Car, Dog…"
          value={draft}
          disabled={disabled}
          onChange={(event) => {
            setDraft(event.target.value);
            setError(null);
          }}
          onKeyDown={addOnEnter}
        />
        <button type="button" className="button button--quiet" onClick={addTerm} disabled={disabled || !draft.trim()}>
          Thêm
        </button>
        <datalist id="object-label-options">
          {labels.map((label) => (
            <option key={label} value={label} />
          ))}
        </datalist>
      </div>

      {terms.length > 0 && (
        <ul className="object-query__terms" aria-label="Object cần có">
          {terms.map((term, index) => (
            <li key={term.label}>
              <span>{term.label}</span>
              <label>
                <span aria-hidden="true">≥</span>
                <select
                  aria-label={`Số lượng tối thiểu ${term.label}`}
                  value={term.min_count}
                  disabled={disabled}
                  onChange={(event) => updateMinCount(index, Number(event.target.value))}
                >
                  {MIN_COUNT_OPTIONS.map((count) => (
                    <option key={count} value={count}>
                      {count}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                aria-label={`Bỏ ${term.label}`}
                disabled={disabled}
                onClick={() => onChange(terms.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      {autoObjects && !disabled && (
        <small className="object-query__hint">
          Enhance query sẽ tự thêm object từ câu truy vấn.
        </small>
      )}
      {error && <small className="object-query__error">{error}</small>}
      {indexUnavailable && (
        <small className="object-query__error">
          Chưa có object index. Chạy scripts/build_object_index.py rồi khởi động lại backend.
        </small>
      )}
    </div>
  );
}
