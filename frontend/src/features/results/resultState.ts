interface IdentifiedResult {
  result_id: string;
  answer?: string;
}

export interface ResultEditorState {
  order: string[];
  answers: Record<string, string>;
}

export type ResultEditorAction =
  | { type: "initialize"; results: IdentifiedResult[] }
  | { type: "move"; activeId: string; overId: string }
  | { type: "set-answer"; resultId: string; answer: string };

export function createResultEditorState(results: IdentifiedResult[]): ResultEditorState {
  const order = results.map((result) => result.result_id);
  return {
    order,
    answers: Object.fromEntries(
      results.map((result) => [result.result_id, result.answer ?? ""]),
    ),
  };
}

export function moveResult(
  order: string[],
  activeId: string,
  overId: string,
): string[] {
  const fromIndex = order.indexOf(activeId);
  const toIndex = order.indexOf(overId);
  if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return order;

  const next = [...order];
  const [moved] = next.splice(fromIndex, 1);
  if (moved === undefined) return order;
  next.splice(toIndex, 0, moved);
  return next;
}

export function resultEditorReducer(
  state: ResultEditorState,
  action: ResultEditorAction,
): ResultEditorState {
  switch (action.type) {
    case "initialize":
      return createResultEditorState(action.results);
    case "move":
      return { ...state, order: moveResult(state.order, action.activeId, action.overId) };
    case "set-answer":
      return {
        ...state,
        answers: { ...state.answers, [action.resultId]: action.answer },
      };
  }
}
