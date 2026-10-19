import { useRef } from "react";
import { createPortal } from "react-dom";

import { useModalAccessibility } from "../results/useModalAccessibility";

const SHORTCUTS: { keys: string[]; action: string }[] = [
  { keys: ["/"], action: "Đưa con trỏ vào ô truy vấn" },
  { keys: ["Enter"], action: "Tìm (Shift+Enter xuống dòng)" },
  { keys: ["←", "→", "↑", "↓"], action: "Chuyển giữa các ảnh kết quả" },
  { keys: ["Home", "End"], action: "Về ảnh đầu / cuối" },
  { keys: ["Enter"], action: "Mở ảnh đang chọn" },
  { keys: ["←", "→"], action: "Trong chi tiết: keyframe trước / sau (frame khi đang phát video)" },
  { keys: ["Shift", "←/→"], action: "Trong chi tiết: luôn theo keyframe" },
  { keys: ["Esc"], action: "Đóng cửa sổ đang mở" },
  { keys: ["?"], action: "Mở bảng này" },
];

export function ShortcutsHelp({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useModalAccessibility({ dialogRef, initialFocusRef: closeRef, onClose });

  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className="shortcuts"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        tabIndex={-1}
      >
        <header className="shortcuts__head">
          <h2 id="shortcuts-title">Phím tắt</h2>
          <button
            ref={closeRef}
            type="button"
            className="button button--icon"
            onClick={onClose}
            aria-label="Đóng"
          >
            ×
          </button>
        </header>
        <dl className="shortcuts__list">
          {SHORTCUTS.map(({ keys, action }) => (
            <div key={action}>
              <dt>
                {keys.map((key) => (
                  <kbd key={key}>{key}</kbd>
                ))}
              </dt>
              <dd>{action}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>,
    document.body,
  );
}
