/**
 * The viz registry's manifests.
 *
 * This is where the design system stops being documentation and becomes
 * runtime infrastructure. One manifest serves two readers:
 *
 *   - the drag-and-drop builder, which renders `channels` as drop targets and
 *     refuses invalid drops, so there is no per-chart builder code;
 *   - the agent, which reads `goodFor` / `notFor` / `invariant` to choose a
 *     mark, and the validator, which uses the same fields to reject one.
 *
 * `notFor` earns its place: it is lifted from the rules that say *why* a mark
 * is wrong, which is the part an LLM cannot infer from a chart name.
 *
 * Manifests are eager on purpose — metadata has to be readable without paying
 * to load the component. Components are lazy; see registry.ts.
 */

export type ChannelKind = "dimension" | "measure" | "period" | "any";

export interface Channel {
  accepts: ChannelKind;
  required: boolean;
  count?: number;
  cardinality?: [number, number];
  note?: string;
}

export interface VizManifest {
  id: string;
  name: string;
  description: string;
  channels: Record<string, Channel>;
  goodFor: string[];
  notFor: string[];
  invariant?: string;
  /** Refuse rather than render illegibly. */
  maxRows: number;
  costClass: "cheap" | "moderate" | "expensive";
  /** Needs a two-period query to mean anything. */
  needsCompare: boolean;
  /** Renders from another block's selection rather than its own query. */
  derivesFromSource?: boolean;
}

export const manifests: Record<string, VizManifest> = {
  "mark.dumbbell": {
    id: "mark.dumbbell",
    name: "Dumbbell",
    description: "Two measured observations per category, joined by a connector.",
    channels: {
      y: { accepts: "dimension", required: true, cardinality: [1, 40] },
      x: { accepts: "measure", required: true, count: 1 },
      series: {
        accepts: "period",
        required: true,
        count: 2,
        note: "exactly two observations",
      },
    },
    goodFor: ["two measured points in time", "before and after by category"],
    notFor: [
      "three or more periods — use a slope or a line",
      "unordered magnitude — use a bar",
      "a single observation — use a bar or a big number",
    ],
    invariant:
      "The connector length IS the variance. Never scale it independently of the dots, and never draw a trend line through two observations.",
    maxRows: 40,
    costClass: "cheap",
    needsCompare: true,
  },

  "mark.bar": {
    id: "mark.bar",
    name: "Bar",
    description: "Magnitude by category, optionally with a comparison period.",
    channels: {
      y: { accepts: "dimension", required: true, cardinality: [1, 30] },
      x: { accepts: "measure", required: true, count: 1 },
    },
    goodFor: ["ranked magnitude by category", "composition at one point in time"],
    notFor: [
      "emphasising change between two dates — use a dumbbell",
      "more than about thirty categories — use a table",
    ],
    maxRows: 30,
    costClass: "cheap",
    needsCompare: false,
  },

  "big.number": {
    id: "big.number",
    name: "Big number",
    description: "One figure, with its change against the comparison period.",
    channels: {
      x: { accepts: "measure", required: true, count: 1 },
    },
    goodFor: ["a single headline figure", "a total that leads a section"],
    notFor: [
      "a figure nobody acts on — a row of decorative tiles buries the page",
      "anything with more than one dimension value — use a bar",
    ],
    invariant:
      "Absolute change leads, percentage follows. On counts a percentage alone lies: 2 to 4 is '+100%'.",
    maxRows: 1,
    costClass: "cheap",
    needsCompare: false,
  },

  "briefing.band": {
    id: "briefing.band",
    name: "Briefing band",
    description: "Leads with the written answer, before any grid.",
    channels: {
      y: { accepts: "dimension", required: true, cardinality: [1, 30] },
      x: { accepts: "measure", required: true, count: 1 },
    },
    goodFor: [
      "the top of a page whose job is 'what changed, and why'",
      "stating the conclusion before the evidence",
    ],
    notFor: ["detail a reader needs to compare precisely — put a mark below it"],
    invariant:
      "Lead with the answer. The page opens with a written summary, not a grid.",
    maxRows: 30,
    costClass: "cheap",
    needsCompare: true,
  },

  "mark.line": {
    id: "mark.line",
    name: "Line",
    description: "A measure over a real time dimension, optionally split into series.",
    channels: {
      x: { accepts: "dimension", required: true, count: 1, note: "must be a time dimension" },
      y: { accepts: "measure", required: true, count: 1 },
      series: { accepts: "dimension", required: false, cardinality: [1, 5] },
    },
    goodFor: ["shape and trend over many observations", "when the change is gradual"],
    notFor: [
      "exactly two dates — use a dumbbell; a line there invents data nobody measured",
      "unordered categories — a line implies the x axis has an order",
      "more than about five series — the lines stop being separable",
    ],
    invariant:
      "The x axis must be genuinely ordered and evenly spaced, and every gridline must name a value the chart reaches.",
    maxRows: 2000,
    costClass: "moderate",
    needsCompare: false,
  },

  "mark.matrix": {
    id: "mark.matrix",
    name: "Matrix",
    description: "One measure across two dimensions, shaded by magnitude.",
    channels: {
      y: { accepts: "dimension", required: true, cardinality: [1, 20] },
      x: { accepts: "dimension", required: true, cardinality: [1, 12] },
      value: { accepts: "measure", required: true, count: 1 },
    },
    goodFor: ["finding the hot cell in a two-way breakdown", "coverage and gaps"],
    notFor: [
      "precise comparison — colour cannot be read to two significant figures",
      "one dimension — use a bar",
      "high cardinality on either axis — it becomes a wall",
    ],
    invariant:
      "Colour is a single-hue sequential ramp carrying magnitude only, and every cell prints its value: colour alone is unreadable for many viewers.",
    maxRows: 240,
    costClass: "cheap",
    needsCompare: false,
  },

  "table.grid": {
    id: "table.grid",
    name: "Table",
    description: "Exact values across several metrics.",
    channels: {
      y: { accepts: "dimension", required: true, cardinality: [1, 500] },
      x: { accepts: "measure", required: false },
    },
    goodFor: ["exact lookup", "several metrics at once", "long tails"],
    notFor: ["showing shape or trend — a reader cannot see it in digits"],
    maxRows: 500,
    costClass: "cheap",
    needsCompare: false,
  },

  "panel.explain": {
    id: "panel.explain",
    name: "Explain panel",
    description:
      "Explains the selected mark, grounded in the compiled SQL, the returned rows and the metric definitions.",
    channels: {},
    goodFor: [
      "answering 'why did this move' next to the thing that moved",
      "showing the definition a figure was computed from",
    ],
    notFor: ["free-form chat — it explains what is on screen, nothing else"],
    invariant:
      "Every claim is grounded in the block's own query, result and metric definitions. It never reaches the warehouse itself.",
    maxRows: 1,
    costClass: "cheap",
    needsCompare: false,
    derivesFromSource: true,
  },
};

export function manifestFor(vizId: string): VizManifest | undefined {
  return manifests[vizId];
}
