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

/**
 * A knob on a chart.
 *
 * Declared, typed and defaulted here so one generic inspector can render a
 * control for it, the agent can set it without guessing, and adding a mark
 * still costs zero builder code. An undeclared option is not customisable —
 * that is the point.
 */
export interface OptionSpec {
  type: "boolean" | "number" | "select" | "string";
  label: string;
  default: boolean | number | string;
  /** For type: "select". */
  choices?: { value: string; label: string }[];
  min?: number;
  max?: number;
  step?: number;
  /** Shown under the control. Say what it is FOR, not what it does. */
  help?: string;
}

export interface VizManifest {
  id: string;
  name: string;
  description: string;
  channels: Record<string, Channel>;
  /** What a viewer or an agent may change about this mark. */
  options: Record<string, OptionSpec>;
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
    options: {
      showSeverity: { type: "boolean", label: "Severity chip", default: true,
        help: "How far outside normal each row sits." },
      showPercent: { type: "boolean", label: "Percentage alongside change", default: true,
        help: "Absolute change always leads; this adds the percentage after it." },
      labelWidth: { type: "number", label: "Label column width", default: 130,
        min: 80, max: 320, step: 10 },
      connectorWeight: { type: "select", label: "Connector weight", default: "regular",
        choices: [{ value: "light", label: "Light" }, { value: "regular", label: "Regular" },
                  { value: "heavy", label: "Heavy" }],
        help: "The connector length is the variance. Weight is styling only." },
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
    options: {
      showGhost: { type: "boolean", label: "Comparison outline", default: true,
        help: "The previous period as a quiet outline behind each bar." },
      showValue: { type: "boolean", label: "Value labels", default: true },
      showDelta: { type: "boolean", label: "Change", default: true },
      labelWidth: { type: "number", label: "Label column width", default: 130,
        min: 80, max: 320, step: 10 },
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
    options: {
      size: { type: "select", label: "Figure size", default: "large",
        choices: [{ value: "medium", label: "Medium" }, { value: "large", label: "Large" },
                  { value: "hero", label: "Hero" }] },
      showDelta: { type: "boolean", label: "Change against comparison", default: true },
      showPercent: { type: "boolean", label: "Percentage", default: true },
      goodDirection: { type: "select", label: "Colour the change", default: "metric",
        choices: [{ value: "metric", label: "By the metric's direction" },
                  { value: "none", label: "Never (neutral)" }],
        help: "The model already knows whether up is good. Override only for a deliberately neutral tile." },
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
    options: {
      threshold: { type: "number", label: "Outside-normal threshold", default: 2,
        min: 0.5, max: 5, step: 0.5,
        help: "Standard deviations before a mover is called out. Lower means a noisier page." },
      showChips: { type: "boolean", label: "Mover chips", default: true },
      maxChips: { type: "number", label: "Maximum chips", default: 8, min: 1, max: 20 },
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
    options: {
      showArea: { type: "boolean", label: "Area fill", default: false,
        help: "Only honest for a measure that starts at zero." },
      showEndpoint: { type: "boolean", label: "Emphasise the endpoint", default: true,
        help: "The latest value is what the reader came for." },
      strokeWidth: { type: "number", label: "Line weight", default: 1.75, min: 1, max: 4, step: 0.25 },
      yFromZero: { type: "boolean", label: "Y axis from zero", default: true,
        help: "Off exaggerates small movements. Turn off only deliberately." },
      tickCount: { type: "number", label: "Y gridlines", default: 3, min: 2, max: 6 },
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
    options: {
      showValues: { type: "boolean", label: "Print values in cells", default: true,
        help: "Colour alone is unreadable for many viewers. Turn off only with a legend." },
      intensity: { type: "number", label: "Colour intensity", default: 72, min: 20, max: 100, step: 4 },
      scale: { type: "select", label: "Colour scale", default: "linear",
        choices: [{ value: "linear", label: "Linear" }, { value: "sqrt", label: "Square root" }],
        help: "Square root reveals detail when a few cells dominate." },
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
    options: {
      density: { type: "select", label: "Row density", default: "regular",
        choices: [{ value: "compact", label: "Compact" }, { value: "regular", label: "Regular" }] },
      zebra: { type: "boolean", label: "Alternating rows", default: false },
      showRank: { type: "boolean", label: "Rank column", default: false },
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
    options: {
      showSql: { type: "boolean", label: "Compiled SQL", default: true },
      showDefinitions: { type: "boolean", label: "Metric definitions", default: true },
    },
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
