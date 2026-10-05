import { type MouseEvent as ReactMouseEvent, useCallback, useEffect, useRef, useState } from "react";

const DEFAULT_WIDTH = 400;
const MIN_WIDTH = 280;

function maxWidth(): number {
  return Math.max(800, Math.min(Math.round(window.innerWidth * 0.65), 1050));
}

/**
 * Sidebar width with drag-to-resize. The "normal" width is the one the user chose for the
 * regular form; wider modes (the KIS plan editor) widen temporarily and restore it afterwards.
 */
export function useResizableSidebar() {
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [normalWidth, setNormalWidth] = useState(DEFAULT_WIDTH);
  const [isResizing, setIsResizing] = useState(false);
  const stopDragRef = useRef<(() => void) | null>(null);

  // Remove the document listeners if the component unmounts in the middle of a drag.
  useEffect(() => () => stopDragRef.current?.(), []);

  /** Start a drag; ``rememberAsNormal`` stores the result as the regular-form width. */
  const startResizing = useCallback(
    (mouseDownEvent: ReactMouseEvent, rememberAsNormal: boolean) => {
      mouseDownEvent.preventDefault();
      setIsResizing(true);
      const startX = mouseDownEvent.clientX;
      const startWidth = width;
      const root = document.documentElement;

      const doDrag = (dragEvent: MouseEvent) => {
        const next = Math.max(
          MIN_WIDTH,
          Math.min(maxWidth(), startWidth + dragEvent.clientX - startX),
        );
        setWidth(next);
        if (rememberAsNormal) setNormalWidth(next);
      };
      const stopDrag = () => {
        root.removeEventListener("mousemove", doDrag);
        root.removeEventListener("mouseup", stopDrag);
        document.body.style.cursor = "";
        stopDragRef.current = null;
        setIsResizing(false);
      };

      root.addEventListener("mousemove", doDrag);
      root.addEventListener("mouseup", stopDrag);
      document.body.style.cursor = "col-resize";
      stopDragRef.current = stopDrag;
    },
    [width],
  );

  const widenTo = useCallback((minimum: number) => {
    setWidth((current) => Math.max(current, minimum));
  }, []);

  const restoreNormal = useCallback(() => setWidth(normalWidth), [normalWidth]);

  return { width, isResizing, startResizing, widenTo, restoreNormal };
}
