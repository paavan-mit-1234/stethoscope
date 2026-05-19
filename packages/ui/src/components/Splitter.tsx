import { useCallback, useRef } from "react";

// 3px drag handle, no animation (PRD 8.4: "drag, snap, done").
export function Splitter({
  axis,
  onDelta,
}: {
  axis: "v" | "h";
  onDelta: (px: number) => void;
}) {
  const dragging = useRef(false);

  const onMove = useCallback(
    (e: PointerEvent) => {
      if (!dragging.current) return;
      onDelta(axis === "v" ? e.movementX : e.movementY);
    },
    [axis, onDelta],
  );

  const stop = useCallback(() => {
    dragging.current = false;
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", stop);
  }, [onMove]);

  const start = useCallback(() => {
    dragging.current = true;
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", stop);
  }, [onMove, stop]);

  return <div className={axis === "v" ? "splitter-v" : "splitter-h"} onPointerDown={start} />;
}
