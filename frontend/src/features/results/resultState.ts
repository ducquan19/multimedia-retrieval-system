// Keep move-by controls implemented but hidden until the manual buttons are needed again.
export const SHOW_MOVE_CONTROLS = false;

interface IdentifiedResult {
  result_id: string;
  answer?: string;
}

export interface ResultEditorState {
  initialOrder: string[];
  order: string[];
  answers: Record<string, string>;
}

export type ResultEditorAction =
  | { type: "initialize"; results: IdentifiedResult[] }
  | { type: "move"; activeId: string; overId: string }
  | { type: "move-by"; resultId: string; offset: -1 | 1 }
  | { type: "set-answer"; resultId: string; answer: string }
  | { type: "reset-order" };

export function createResultEditorState(results: IdentifiedResult[]): ResultEditorState {
  const order = results.map((result) => result.result_id);
  return {
    initialOrder: order,
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
    case "move-by": {
      const currentIndex = state.order.indexOf(action.resultId);
      const targetId = state.order[currentIndex + action.offset];
      if (currentIndex < 0 || targetId === undefined) return state;
      return {
        ...state,
        order: moveResult(state.order, action.resultId, targetId),
      };
    }
    case "set-answer":
      return {
        ...state,
        answers: { ...state.answers, [action.resultId]: action.answer },
      };
    case "reset-order":
      return { ...state, order: [...state.initialOrder] };
  }
}
