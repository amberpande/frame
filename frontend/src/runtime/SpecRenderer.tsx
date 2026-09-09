import { useEffect } from "react";
import type { DashboardSpec } from "../spec/types";
import BlockHost from "./BlockHost";
import { useSelection } from "./selection";
import { blockState, useDashboardData } from "./useDashboardData";

interface Props {
  spec: DashboardSpec;
  params: Record<string, unknown>;
  onResolved?: (resolved: Record<string, unknown>) => void;
}

/**
 * The whole renderer.
 *
 * There is no per-dashboard code path anywhere below this component — the spec
 * is the only input, and adding the thousandth dashboard adds nothing here.
 */
export default function SpecRenderer({ spec, params, onResolved }: Props) {
  const { selections } = useSelection();
  const { blocks, tiers, slowestMs } = useDashboardData(spec, params, selections);

  // Surface the params the server actually resolved (@latest_close and friends)
  // so the controls can show real dates rather than the symbols.
  const firstMeta = Object.values(blocks).find((b) => b.meta)?.meta;
  const resolvedKey = firstMeta ? JSON.stringify(firstMeta.params) : null;
  useEffect(() => {
    if (resolvedKey && onResolved) onResolved(JSON.parse(resolvedKey));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedKey]);

  const warehouse = tiers.warehouse ?? 0;
  const cached = tiers["result-cache"] ?? 0;
  const total = warehouse + cached;

  return (
    <>
      <div className="vd-grid">
        {spec.blocks.map((block) => (
          <BlockHost
            key={block.id}
            spec={spec}
            block={block}
            state={blockState(blocks, block.id)}
            sourceState={blockState(blocks, block.source?.block)}
          />
        ))}
      </div>

      {total > 0 && (
        <p className="vd-tiermix">
          {total} block {total === 1 ? "query" : "queries"} · {cached} served from cache,{" "}
          {warehouse} from the warehouse · slowest {Math.round(slowestMs)}ms
        </p>
      )}
    </>
  );
}
