import { type TextareaHTMLAttributes, useLayoutEffect, useRef } from "react";

type AutoGrowTextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

/**
 * A textarea that grows with its text. `rows` sets the minimum height and CSS `max-height`
 * the maximum; past that it scrolls. The height is recomputed when the text changes and when
 * the box gets narrower or wider (the text wraps onto a different number of lines).
 */
export function AutoGrowTextarea({ className, ...props }: AutoGrowTextareaProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const textarea = ref.current;
    if (!textarea) return;
    fitToContent(textarea);
  }, [props.value]);

  useLayoutEffect(() => {
    const textarea = ref.current;
    if (!textarea || typeof ResizeObserver === "undefined") return;
    let width = textarea.clientWidth;
    const observer = new ResizeObserver(() => {
      // Only width changes matter; our own height changes must not loop.
      if (textarea.clientWidth === width) return;
      width = textarea.clientWidth;
      fitToContent(textarea);
    });
    observer.observe(textarea);
    return () => observer.disconnect();
  }, []);

  return (
    <textarea
      ref={ref}
      className={className ? `auto-grow ${className}` : "auto-grow"}
      {...props}
    />
  );
}

function fitToContent(textarea: HTMLTextAreaElement) {
  // Collapse to the rows-based minimum first, so the textarea can also shrink.
  textarea.style.height = "auto";
  const content = textarea.scrollHeight;
  if (content === 0) return; // not laid out (hidden, or a test DOM without layout)
  const borders = textarea.offsetHeight - textarea.clientHeight;
  const maxHeight = Number.parseFloat(getComputedStyle(textarea).maxHeight);
  const wanted = content + borders;
  textarea.style.height = `${wanted}px`;
  textarea.style.overflowY = Number.isFinite(maxHeight) && wanted > maxHeight ? "auto" : "hidden";
}
