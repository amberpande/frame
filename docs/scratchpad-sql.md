# Scratchpad SQL

A block can hold SQL a person wrote instead of a governed query. This document
is about what that costs and what makes it safe, because it is the one place in
the platform where SQL does not come from the compiler.

---

## The condition

**Hand-written SQL must execute as the person who wrote it, not as the service.**

Everything else here is secondary. If the service connects to Snowflake with one
shared role and runs user SQL under it, then any user can read everything the
service can read, and row access policies are bypassed entirely — a viewer
restricted to EMEA writes `SELECT * FROM fct_exception` and sees every region.

`Identity.warehouse_role` is the hook. The Snowflake engine issues
`USE ROLE <that role>` before the statement and refuses outright if the identity
has none:

```
PermissionError: contractor@example.com has no warehouse_role;
refusing to run hand-written SQL as the shared service role
```

**What you must set up in Snowflake:**

1. A role per access scope — you likely already have these.
2. Each role **granted to the service user**, or `USE ROLE` will fail.
3. Those roles holding **SELECT only**. No `INSERT`, no DDL. The Python checks
   below are not a substitute for this.
4. Row access policies attached to the tables, so restriction follows the role
   rather than depending on the application.

The pooled connection restores the service role in a `finally` block, and
discards the session if that fails — an assumed role must not leak into the next
request that borrows the connection.

**No per-user role means no scratchpad SQL.** That is the correct failure. The
alternative is a platform where row-level security is optional.

---

## What is actually contained

| Control | What it does | What it does not do |
|---|---|---|
| Single statement | Rejects `;` and anything after it | Stop a determined author |
| Must start `SELECT`/`WITH` | Rejects DDL and DML outright | Prove the statement only reads |
| Forbidden-keyword scan | Catches `GRANT`, `DELETE`, `COPY` hidden mid-query | Catch obfuscation |
| Row cap by wrapping | `SELECT * FROM (…) LIMIT n` — always holds | Bound bytes scanned |
| Statement timeout | Kills a runaway query | Stop it costing credits first |
| Query tag | `frame:adhoc:<spec>:<block>` — cost is attributable | |
| Never cached across users | Results are not shared between identities | |

The string checks are defence in depth and the code says so. **They are not the
boundary.** No amount of SQL inspection makes arbitrary SQL safe; the role does.

---

## What you give up

A scratchpad block is not a governed metric, and the differences matter:

- **No grain enforcement.** Nothing stops a query slicing a pre-aggregated table
  in a way that double-counts. The guard that catches this for governed metrics
  does not apply.
- **No shared cache.** Results are keyed per user, so ten people running the
  same query cost ten warehouse queries. At scale this is the expensive path —
  see the capacity plan.
- **No agent.** The planner works over the semantic model. It cannot reason
  about, explain, or refactor a hand-written query.
- **No comparability.** Two blocks called "revenue" may compute different
  things. This is exactly the drift the semantic layer exists to remove.

Because of that last point, a scratchpad block is **labelled everywhere it
appears**: an `SQL` badge on the block header, `governed: false` in the response
meta, and a warning in the inspector. A number that did not come through the
compiler should never look like one that did.

---

## Using it

In the builder: **Edit → Add a block → + SQL block**, then write the query. The
inspector asks *why this is not a governed metric* — optional, but a dashboard
full of unexplained SQL blocks is the signal that the model is missing
something.

In a spec:

```json
{
  "id": "by-tier",
  "viz": "mark.bar",
  "at": { "x": 0, "y": 0, "w": 12, "h": 6 },
  "title": "Written by hand",
  "sql": {
    "sql": "SELECT vendor_tier, COUNT(*) AS breaks FROM ANALYTICS.OPS.FCT_EXCEPTION WHERE status IN ('OPEN','PENDING') GROUP BY 1 ORDER BY 2 DESC",
    "note": "one-off investigation"
  },
  "encode": { "y": "vendor_tier", "x": "breaks" }
}
```

A block has exactly one of `query`, `sql` or `source`; declaring both a query
and SQL is refused at publish time.

Results are shaped like any other block — text columns become dimensions,
numbers become measures, and `__period` / `__rank` are added — so a scratchpad
query renders in a bar, a line, a matrix or a table with no special-casing.

---

## The path back

A scratchpad query that keeps being useful should stop being a scratchpad
query. Two ways out, in order of preference:

1. **Add a measure to the semantic model.** The right answer when the query
   computes something the business has a name for. It then gets a grain, an
   owner, a test, the shared cache and the agent.
2. **Add a `calc.*` calculation to the spec.** The right answer when the query
   is only combining metrics that already exist — a ratio or a share. See
   [`authoring-specs.md`](./authoring-specs.md#defining-a-metric-from-the-dashboard).

Track the count. Scratchpad blocks are a demand signal:

```bash
grep -l '"sql"' backend/specs/*.json | wc -l
```

A handful is healthy exploration. A steadily rising number means people are
routing around the semantic layer, and the question to ask is what it is
missing — not how to make SQL blocks nicer.
