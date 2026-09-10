import { useState } from "react";
import type { Block } from "../spec/types";
import type { Editor } from "./useEditor";

interface Props {
  block: Block;
  editor: Editor;
}

/**
 * The scratchpad SQL editor.
 *
 * This is the one place in the product where a person writes SQL, and the UI
 * should say so rather than hide it. A block backed by this is not compiled,
 * not covered by the semantic model's grain rules, and not comparable with a
 * governed metric of the same name — so it is labelled everywhere it appears.
 *
 * What bounds it is the warehouse role the query runs as, not anything here.
 */
export default function SqlEditor({ block, editor }: Props) {
  const [draft, setDraft] = useState(block.sql?.sql ?? "");
  const dirty = draft !== (block.sql?.sql ?? "");

  return (
    <>
      <p className="vd-inspector__warn">
        Ungoverned. This runs as you, so it can read exactly what your warehouse
        role can read — no more, and no less.
      </p>

      <label className="vd-inspector__field">
        <span>Query</span>
        <textarea
          className="vd-input vd-sql__input"
          rows={10}
          spellCheck={false}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={"SELECT team, COUNT(*) AS n\nFROM ANALYTICS.OPS.FCT_EXCEPTION\nGROUP BY 1"}
        />
        <em className="vd-inspector__hint">
          One statement, read-only. Results are capped and never shared between
          users. Text columns become dimensions, numbers become measures.
        </em>
      </label>

      <label className="vd-inspector__field">
        <span>Why not a governed metric?</span>
        <input
          className="vd-input"
          value={block.sql?.note ?? ""}
          placeholder="e.g. one-off investigation"
          onChange={(e) =>
            editor.patchBlock(block.id, {
              sql: { sql: block.sql?.sql ?? "", note: e.target.value || undefined },
            })
          }
        />
        <em className="vd-inspector__hint">
          A dashboard full of unexplained SQL blocks is the signal that the
          semantic model is missing something.
        </em>
      </label>

      <div className="vd-calc__actions">
        <button
          type="button"
          className="vd-btn vd-btn--ghost"
          disabled={!dirty}
          onClick={() => setDraft(block.sql?.sql ?? "")}
        >
          Revert
        </button>
        <button
          type="button"
          className="vd-btn"
          disabled={!dirty || !draft.trim()}
          onClick={() =>
            editor.patchBlock(block.id, { sql: { sql: draft, note: block.sql?.note } })
          }
        >
          Run
        </button>
      </div>
    </>
  );
}
