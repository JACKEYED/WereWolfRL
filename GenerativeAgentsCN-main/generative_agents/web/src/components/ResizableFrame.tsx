import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

type ResizeHandle = "n" | "e" | "s" | "w" | "nw" | "ne" | "sw" | "se";

interface FrameSize {
  width: number;
  height: number | null;
}

interface DragState {
  handle: ResizeHandle;
  startClientX: number;
  startClientY: number;
  startWidth: number;
  startHeight: number;
}

interface Props {
  children: ReactNode;
  defaultWidth: number;
  id: string;
  minHeight?: number;
  minWidth?: number;
}

const HANDLES: ResizeHandle[] = ["n", "e", "s", "w", "nw", "ne", "sw", "se"];
const STORAGE_PREFIX = "jiangnan-panel-frame:";

export function ResizableFrame({
  children,
  defaultWidth,
  id,
  minHeight = 260,
  minWidth = 240,
}: Props) {
  const frameRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<FrameSize>(() => loadFrameSize(id, defaultWidth));
  const [drag, setDrag] = useState<DragState | null>(null);

  useEffect(() => {
    try {
      window.localStorage.setItem(`${STORAGE_PREFIX}${id}`, JSON.stringify(size));
    } catch {
      // ignore unavailable storage
    }
  }, [id, size]);

  useEffect(() => {
    if (!drag) return;

    const previousUserSelect = document.body.style.userSelect;
    document.body.style.userSelect = "none";

    const handlePointerMove = (event: PointerEvent) => {
      const dx = event.clientX - drag.startClientX;
      const dy = event.clientY - drag.startClientY;
      setSize({
        width: clamp(resizedWidth(drag.handle, drag.startWidth, dx), minWidth, 1600),
        height: clamp(resizedHeight(drag.handle, drag.startHeight, dy), minHeight, 1200),
      });
    };

    const handlePointerUp = () => setDrag(null);
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp, { once: true });
    window.addEventListener("pointercancel", handlePointerUp, { once: true });

    return () => {
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
  }, [drag, minHeight, minWidth]);

  const beginResize = (handle: ResizeHandle, event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) return;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Window-level listeners still complete the drag.
    }
    setDrag({
      handle,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startWidth: rect.width,
      startHeight: rect.height,
    });
  };

  return (
    <div
      ref={frameRef}
      className={`resizable-frame${drag ? " resizing" : ""}`}
      style={{
        flexBasis: `${size.width}px`,
        width: `${size.width}px`,
        height: size.height === null ? undefined : `${size.height}px`,
      }}
    >
      <div className="resizable-frame-content">{children}</div>
      <div className="frame-resize-handles" aria-hidden="true">
        {HANDLES.map((handle) => (
          <button
            type="button"
            key={handle}
            className={`frame-resize-handle frame-resize-${handle}`}
            onPointerDown={(e) => beginResize(handle, e)}
            tabIndex={-1}
          />
        ))}
      </div>
    </div>
  );
}

function loadFrameSize(id: string, defaultWidth: number): FrameSize {
  if (typeof window === "undefined") {
    return { width: defaultWidth, height: null };
  }
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${id}`);
    if (!raw) return { width: defaultWidth, height: null };
    const parsed = JSON.parse(raw) as Partial<FrameSize>;
    return {
      width: clamp(Number(parsed.width ?? defaultWidth), 220, 1600),
      height:
        parsed.height === null || parsed.height === undefined
          ? null
          : clamp(Number(parsed.height), 220, 1200),
    };
  } catch {
    return { width: defaultWidth, height: null };
  }
}

function resizedWidth(handle: ResizeHandle, startWidth: number, dx: number): number {
  if (handle.includes("e")) return startWidth + dx;
  if (handle.includes("w")) return startWidth - dx;
  return startWidth;
}

function resizedHeight(handle: ResizeHandle, startHeight: number, dy: number): number {
  if (handle.includes("s")) return startHeight + dy;
  if (handle.includes("n")) return startHeight - dy;
  return startHeight;
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}
