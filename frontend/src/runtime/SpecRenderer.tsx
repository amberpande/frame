import { useCallback, useEffect, useRef, useState } from "react";
import type { DashboardSpec, Placement } from "../spec/types";
import BlockHost from "./BlockHost";
import { useSelection } from "./selection";
import { blockState, useDashboardData } from "./useDashboardData";
import type { Editor } from "../builder/useEditor";

const ROW_HEIGHT = 62;
const GAP = 14;

interface Props {
  spec: DashboardSpec;
  params: Record<string, unknown>;
  onResolved?: (resolved: Record<string, unknown>) => void;
  /** Present only in edit mode. */
  editor?: Editor;
}

interface Drag {
  blockId: string;
  mode: "move" | "resize";
  startX: number;
  startY: number;
  from: Placement;
}

/**
 * The whole renderer.
 *
 * There is no per-dashboard code path anywhere below this component — the spec
 * is the only input, and adding the thousandth dashboard adds nothing here.
 * In edit mode the same tree renders the same blocks; only affordances are
 * added, so what you edit is exactly what viewers get.
 */
export default function SpecRenderer({ spec, params, onResolved, editor }: Props) {
  const { selections } = useSelection();
  const { blocks, tiers, slowestMs } = useDashboardData(spec, params, selections);
  const gridRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);

  const firstMeta = Object.values(blocks).find((b) => b.meta)?.meta;
  const resolvedKey = firstMeta ? JSON.stringify(firstMeta.params) : null;
  useEffect(() => {
    if (resolvedKey && onResolved) onResolved(JSON.parse(resolvedKey));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedKey]);

  const beginDrag = useCallback(
    (blockId: string, mode: "move" | "resize", e: React.PointerEvent) => {
      const block = spec.blocks.find((b) => b.id === blockId);
      if (!block) return;
      e.preventDefault();
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
      setDrag({ blockId, mode, startX: e.clientX, startY: e.clientY, from: { ...block.at } });
    },
    [spec]
  );

  useEffect(() => {
    if (!drag || !editor) return;
    const grid = gridRef.current;
    if (!grid) return;

    // One column is (width - 11 gaps) / 12. Pointer deltas convert to whole
    // cells, so a block can only ever land on the grid the spec describes.
    const cellW = (grid.clientWidth - GAP * 11) / 12;
    const cellH = ROW_HEIGHT + GAP;

    const onMove = (e: PointerEvent) => {
      const dx = Math.round((e.clientX - drag.startX) / cellW);
      const dy = Math.round((e.clientY - drag.startY) / cellH);
      if (drag.mode === "move") {
        editor.place(drag.blockId, {
          ...drag.from,
          x: drag.from.x + dx,
          y: Math.max(0, drag.from.y + dy),
        });
      } else {
        editor.place(drag.blockId, {
          ...drag.from,
          w: Math.max(1, drag.from.w + dx),
          h: Math.max(1, drag.from.h + dy),
        });
      }
    };
    const stop = () => setDrag(null);

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
  }, [drag, editor]);

  const warehouse = tiers.warehouse ?? 0;
  const cached = tiers["result-cache"] ?? 0;
  const total = warehouse + cached;

  return (
    <>
      <div
        ref={gridRef}
        className={`vd-grid${editor?.editing ? " is-editing" : ""}${drag ? " is-dragging" : ""}`}
      >
        {spec.blocks.map((block) => (
          <BlockHost
            key={block.id}
            spec={spec}
            block={block}
            state={blockState(blocks, block.id)}
            sourceState={blockState(blocks, block.source?.block)}
            editing={Boolean(editor?.editing)}
            isSelected={editor?.selectedId === block.id}
            onSelectBlock={() => editor?.select(block.id)}
            onDragHandle={(mode, e) => beginDrag(block.id, mode, e)}
          />
        ))}
      </div>

      {total > 0 && !editor?.editing && (
        <p className="vd-tiermix">
          {total} block {total === 1 ? "query" : "queries"} · {cached} served from cache,{" "}
          {warehouse} from the warehouse · slowest {Math.round(slowestMs)}ms
        </p>
      )}
    </>
  );
}
