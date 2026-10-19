import type { KeyboardEvent } from "react";

/** Enter submits the search form; Shift+Enter (or an IME composition) keeps a new line. */
export function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement>) {
  if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
    return;
  }
  event.preventDefault();
  event.currentTarget.form?.requestSubmit();
}
