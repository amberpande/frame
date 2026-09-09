import { Suspense } from "react";
import type { Block, DashboardSpec } from "../spec/types";
import { resolve } from "../viz/registry";
import { useSelection } from "./selection";
import type { BlockState } from "./useDashboardData";

interface Props {
  spec: DashboardSpec;
  block: Block;
  state: BlockState;
  sourceState: BlockState;
}

/**
 * Renders one block of a spec.
 *
 * Everything specific to a visualization lives behind the registry, so this
 * component never grows a branch per chart type. An unknown `viz` id is a
 * first-class state, not a crash: a runtime must survive meeting a spec
 * written against a newer catalogue.
 */
export default function BlockHost({ spec, block, state, sourceState }: Props) {
  const entry = resolve(block.viz);
  const { select, from } = useSelection();

  const style = {
    gridColumn: `${block.at.x + 1} / span ${block.at.w}`,
    gridRow: `${block.at.y + 1} / span ${block.at.h}`,
  };

  if (!entry) {
    return (
      <section className="vd-block vd-block--unknown" style={style}>
        <div className="vd-block__head">
          <h3>{block.title ?? block.id}</h3>
        </div>
        <p className="vd-block__error">
          This runtime has no visualization registered as <code>{block.viz}</code>.
          The spec is fine; the catalogue is behind.
        </p>
      </section>
    );
  }

  const Viz = entry.component;
  const incoming = block.source ? from(block.source.block) : null;
  const own = from(block.id);
  const meta = state.meta;

  return (
    <section className="vd-block" style={style}>
      {(block.title || meta) && (
        <div className="vd-block__head">
          <div>
            {block.title && <h3>{block.title}</h3>}
            {block.subtitle && <p className="vd-block__sub">{block.subtitle}</p>}
            {/* A filtered block that does not say it is filtered invites the
                viewer to read a subset as the whole. */}
            {state.crossFilters.length > 0 && (
              <p className="vd-block__filtered">
                filtered to {state.crossFilters.map((f) => String(f.value)).join(" · ")}
                <button
                  type="button"
                  className="vd-block__clear"
                  onClick={() => block.source && select(block.source.block, null)}
                >
                  clear
                </button>
              </p>
            )}
          </div>
          {meta && (
            <span
              className={`vd-tier vd-tier--${meta.tier}`}
              title={`plan ${meta.planHash} · ${meta.cost.dayPartitions} day partitions · ${meta.rowCount} rows`}
            >
              {meta.tier === "result-cache" ? "cached" : meta.tier}
              <span className="vd-tier__ms">{Math.round(meta.elapsedMs)}ms</span>
            </span>
          )}
        </div>
      )}

      <div className="vd-block__body">
        {state.error ? (
          <p className="vd-block__error">{state.error}</p>
        ) : state.loading ? (
          <div className="vd-skeleton" aria-label="Loading" />
        ) : (
          <Suspense fallback={<div className="vd-skeleton" aria-label="Loading" />}>
            <Viz
              block={block}
              spec={spec}
              table={state.table}
              meta={state.meta}
              selected={own?.group ?? null}
              onSelect={(group) => select(block.id, group)}
              incoming={incoming}
              sourceTable={sourceState.table}
              sourceMeta={sourceState.meta}
            />
          </Suspense>
        )}
      </div>
    </section>
  );
}
