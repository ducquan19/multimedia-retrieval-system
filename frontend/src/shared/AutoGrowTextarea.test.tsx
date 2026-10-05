import { render, screen } from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AutoGrowTextarea } from "./AutoGrowTextarea";

/** jsdom has no layout: pretend each line of text is 20px tall. */
function fakeLayout(textarea: HTMLTextAreaElement) {
  Object.defineProperty(textarea, "scrollHeight", {
    configurable: true,
    get: () => Math.max(1, textarea.value.split("\n").length) * 20,
  });
  Object.defineProperty(textarea, "offsetHeight", { configurable: true, get: () => 2 });
  Object.defineProperty(textarea, "clientHeight", { configurable: true, get: () => 0 });
}

function Harness() {
  const [value, setValue] = useState("");
  return (
    <AutoGrowTextarea
      aria-label="Query"
      rows={1}
      value={value}
      style={{ maxHeight: "70px" }}
      onChange={(event) => {
        fakeLayout(event.currentTarget);
        setValue(event.target.value);
      }}
    />
  );
}

describe("AutoGrowTextarea", () => {
  it("grows with each line, shrinks back and scrolls past its maximum height", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const textarea = screen.getByLabelText<HTMLTextAreaElement>("Query");

    await user.type(textarea, "one{Shift>}{Enter}{/Shift}two");
    // 2 lines of 20px plus 2px of borders.
    expect(textarea.style.height).toBe("42px");
    expect(textarea.style.overflowY).toBe("hidden");

    await user.type(textarea, "{Shift>}{Enter}{/Shift}three{Shift>}{Enter}{/Shift}four");
    expect(textarea.style.height).toBe("82px");
    expect(textarea.style.overflowY).toBe("auto");

    await user.clear(textarea);
    expect(textarea.style.height).toBe("22px");
    expect(textarea).toHaveClass("auto-grow");
  });
});
