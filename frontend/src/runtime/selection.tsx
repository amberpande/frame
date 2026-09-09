import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Group } from "./table";

export interface Selection {
  blockId: string;
  group: Group;
}

interface SelectionStore {
  selections: Record<string, Selection | null>;
  select: (blockId: string, group: Group | null) => void;
  from: (blockId: string) => Selection | null;
}

const Ctx = createContext<SelectionStore | null>(null);

/**
 * Cross-block wiring, kept deliberately small.
 *
 * A block declares `source: { block, on }` in the spec; it reads whatever that
 * block has selected. No block reaches for another block's data directly.
 */
export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selections, setSelections] = useState<Record<string, Selection | null>>({});

  const select = useCallback((blockId: string, group: Group | null) => {
    setSelections((prev) => {
      const existing = prev[blockId];
      if (group && existing?.group.key === group.key) {
        return { ...prev, [blockId]: null }; // click the selected row to clear
      }
      return { ...prev, [blockId]: group ? { blockId, group } : null };
    });
  }, []);

  const from = useCallback((blockId: string) => selections[blockId] ?? null, [selections]);

  const value = useMemo(() => ({ selections, select, from }), [selections, select, from]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSelection(): SelectionStore {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSelection must be used inside a SelectionProvider");
  return ctx;
}
