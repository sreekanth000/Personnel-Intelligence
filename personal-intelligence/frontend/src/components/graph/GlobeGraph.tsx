/**
 * GlobeGraph — D3 force-directed network rendered as a full-screen cosmos/globe visualization.
 * Nodes are colored by entity type, links curve and glow, background has animated stars.
 */
import * as d3 from "d3";
import React, { useEffect, useRef, useState } from "react";
import type { UIGraphEdge, UIGraphNode } from "../../types";

/* ─── Entity color palette ──────────────────────────────────────── */
const ENTITY_COLORS: Record<string, { fill: string; stroke: string; glow: string }> = {
  person:       { fill: "#1e3a5f", stroke: "#3b82f6", glow: "#3b82f6" },
  organization: { fill: "#1e1a3f", stroke: "#818cf8", glow: "#818cf8" },
  project:      { fill: "#052e16", stroke: "#34d399", glow: "#34d399" },
  goal:         { fill: "#3b0764", stroke: "#a78bfa", glow: "#a78bfa" },
  decision:     { fill: "#431407", stroke: "#fb923c", glow: "#fb923c" },
  event:        { fill: "#083344", stroke: "#22d3ee", glow: "#22d3ee" },
  document:     { fill: "#1a1a2e", stroke: "#e879f9", glow: "#e879f9" },
  concept:      { fill: "#1c1917", stroke: "#fbbf24", glow: "#fbbf24" },
  claim:        { fill: "#0f172a", stroke: "#64748b", glow: "#64748b" },
  commitment:   { fill: "#0c4a6e", stroke: "#38bdf8", glow: "#38bdf8" },
  role:         { fill: "#14532d", stroke: "#86efac", glow: "#86efac" },
  location:     { fill: "#451a03", stroke: "#f97316", glow: "#f97316" },
  product:      { fill: "#4a044e", stroke: "#f0abfc", glow: "#f0abfc" },
};

const getColors = (type: string) =>
  ENTITY_COLORS[type?.toLowerCase()] ?? { fill: "#1a2035", stroke: "#4b5563", glow: "#4b5563" };

const NODE_RADIUS = 26;

/* ─── Stable star field (generated once) ───────────────────────── */
const STARS = Array.from({ length: 200 }, (_, i) => ({
  id: i,
  cx: Math.random() * 100,
  cy: Math.random() * 100,
  r:  Math.random() * 1.3 + 0.3,
  o:  Math.random() * 0.45 + 0.15,
  dur: (Math.random() * 3 + 2).toFixed(1),
}));

/* ─── Types ─────────────────────────────────────────────────────── */
interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  type: string;
  metadata: Record<string, unknown>;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  id: string;
  relationship_type: string;
  confidence: number;
  status: string;
}

interface Props {
  nodes: UIGraphNode[];
  edges: UIGraphEdge[];
  onNodeClick: (node: UIGraphNode) => void;
  onEdgeClick: (edge: UIGraphEdge) => void;
  highlightId: string | null;
}

/* ─── Component ─────────────────────────────────────────────────── */
export const GlobeGraph: React.FC<Props> = ({
  nodes,
  edges,
  onNodeClick,
  onEdgeClick,
  highlightId,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef      = useRef<SVGSVGElement>(null);
  const simRef      = useRef<d3.Simulation<SimNode, SimLink> | null>(null);

  // Keep callbacks in refs so d3 handlers always use latest version
  const onNodeClickRef = useRef(onNodeClick);
  const onEdgeClickRef = useRef(onEdgeClick);
  useEffect(() => { onNodeClickRef.current = onNodeClick; }, [onNodeClick]);
  useEffect(() => { onEdgeClickRef.current = onEdgeClick; }, [onEdgeClick]);

  const [dims, setDims] = useState({ w: 1200, h: 800 });

  /* track container dimensions */
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      setDims({ w: r.width || 1200, h: r.height || 800 });
    });
    ro.observe(el);
    const rect = el.getBoundingClientRect();
    if (rect.width > 0) setDims({ w: rect.width, h: rect.height });
    return () => ro.disconnect();
  }, []);

  /* ── Build / rebuild the D3 simulation whenever data or dims change ── */
  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    const { w, h } = dims;

    /* stop previous sim */
    simRef.current?.stop();

    /* prepare data - deep copy so d3 can mutate positions */
    const simNodes: SimNode[] = nodes.map((n, idx) => ({
      id: n.id,
      label: n.label || n.id || "Entity",
      type: n.type || "concept",
      metadata: n.metadata ?? {},
      // Initial positioning near center for smooth simulation startup
      x: (w / 2) + (Math.cos((idx / (nodes.length || 1)) * 2 * Math.PI) * Math.min(w, h) * 0.2) + (Math.random() - 0.5) * 20,
      y: (h / 2) + (Math.sin((idx / (nodes.length || 1)) * 2 * Math.PI) * Math.min(w, h) * 0.2) + (Math.random() - 0.5) * 20,
    }));

    const nodeById = new Map(simNodes.map((n) => [n.id, n]));

    const simLinks: SimLink[] = edges
      .filter((e) => nodeById.has(e.source) && nodeById.has(e.target))
      .map((e) => ({
        id: e.id,
        relationship_type: e.relationship_type,
        confidence: e.confidence,
        status: e.status,
        source: e.source,
        target: e.target,
      }));

    /* ── SVG skeleton (idempotent) ── */
    svg.selectAll(".g-root").remove();

    /* one-time defs */
    let defs = svg.select<SVGDefsElement>("defs");
    if (defs.empty()) defs = svg.append("defs");
    defs.html(""); // reset

    // arrowhead
    defs.append("marker")
      .attr("id", "arr")
      .attr("viewBox", "0 -4 8 8")
      .attr("refX", NODE_RADIUS + 10)
      .attr("refY", 0)
      .attr("markerWidth", 5)
      .attr("markerHeight", 5)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L8,0L0,4")
      .attr("fill", "#374151");

    // glow filter
    const gf = defs.append("filter").attr("id", "node-glow")
      .attr("x", "-50%").attr("y", "-50%").attr("width", "200%").attr("height", "200%");
    gf.append("feGaussianBlur").attr("in", "SourceGraphic").attr("stdDeviation", "5").attr("result", "blur");
    const fm = gf.append("feMerge");
    fm.append("feMergeNode").attr("in", "blur");
    fm.append("feMergeNode").attr("in", "blur");
    fm.append("feMergeNode").attr("in", "SourceGraphic");

    /* ── Zoom ── */
    const root = svg.append("g").attr("class", "g-root");

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 5])
      .on("zoom", (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) => {
        root.attr("transform", event.transform.toString());
      });

    svg.call(zoom).on("dblclick.zoom", null);

    /* ── Link layer ── */
    const linkSel = root.append("g").attr("class", "g-links")
      .selectAll<SVGPathElement, SimLink>("path")
      .data(simLinks, (d) => d.id)
      .enter()
      .append("path")
      .attr("fill", "none")
      .attr("stroke", (d) => {
        const src = nodeById.get(typeof d.source === "string" ? d.source : (d.source as SimNode).id);
        return src ? (getColors(src.type).stroke + "70") : "#37415180";
      })
      .attr("stroke-width", (d) => Math.max(0.8, (d.confidence ?? 0.5) * 2.2))
      .attr("stroke-dasharray", (d) => d.status === "inactive" ? "5 5" : "none")
      .attr("marker-end", "url(#arr)")
      .style("cursor", "pointer")
      .on("click", (_event, d) => {
        const orig = edges.find((e) => e.id === d.id);
        if (orig) onEdgeClickRef.current(orig);
      });

    /* edge labels */
    const edgeLabelSel = root.append("g").attr("class", "g-edge-labels")
      .selectAll<SVGTextElement, SimLink>("text")
      .data(simLinks, (d) => d.id)
      .enter()
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("font-size", "7.5")
      .attr("font-family", "ui-monospace,monospace")
      .attr("fill", "#4b5563")
      .attr("pointer-events", "none")
      .text((d) => (d.relationship_type ?? "").replace(/_/g, " ").toLowerCase());

    /* ── Node layer ── */
    const nodeSel = root.append("g").attr("class", "g-nodes")
      .selectAll<SVGGElement, SimNode>("g.nd")
      .data(simNodes, (d) => d.id)
      .enter()
      .append("g")
      .attr("class", "nd")
      .style("cursor", "pointer")
      .on("click", (_event, d) => {
        const orig = nodes.find((n) => n.id === d.id);
        if (orig) onNodeClickRef.current(orig);
      })
      .call(
        d3.drag<SVGGElement, SimNode>()
          .on("start", (event, d) => {
            if (!event.active) simRef.current?.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
          })
          .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
          .on("end", (event, d) => {
            if (!event.active) simRef.current?.alphaTarget(0);
            d.fx = null; d.fy = null;
          }),
      );

    // outer pulse ring
    nodeSel.append("circle")
      .attr("r", NODE_RADIUS + 10)
      .attr("fill", (d) => getColors(d.type).glow + "15")
      .attr("stroke", (d) => getColors(d.type).glow + "30")
      .attr("stroke-width", 1.5);

    // main node
    nodeSel.append("circle")
      .attr("r", NODE_RADIUS)
      .attr("fill", (d) => getColors(d.type).fill)
      .attr("stroke", (d) => getColors(d.type).stroke)
      .attr("stroke-width", 2)
      .attr("filter", "url(#node-glow)");

    // label
    nodeSel.append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("font-size", "8.5")
      .attr("font-weight", "700")
      .attr("font-family", "Inter,ui-sans-serif,sans-serif")
      .attr("fill", "#f1f5f9")
      .attr("pointer-events", "none")
      .each(function(d) {
        const el = d3.select(this);
        const labelStr = String(d.label || "").trim();
        const words = labelStr.split(/\s+/);
        if (words.length <= 1) {
          el.text(labelStr.length > 12 ? labelStr.slice(0, 11) + "…" : labelStr);
        } else {
          // two-line label
          const line1 = words.slice(0, Math.ceil(words.length / 2)).join(" ");
          const line2 = words.slice(Math.ceil(words.length / 2)).join(" ");
          el.append("tspan").attr("x", 0).attr("dy", "-5").text(
            line1.length > 11 ? line1.slice(0, 10) + "…" : line1
          );
          el.append("tspan").attr("x", 0).attr("dy", "11").text(
            line2.length > 11 ? line2.slice(0, 10) + "…" : line2
          );
        }
      });

    // type badge below
    nodeSel.append("text")
      .attr("y", NODE_RADIUS + 15)
      .attr("text-anchor", "middle")
      .attr("font-size", "7")
      .attr("font-weight", "600")
      .attr("font-family", "ui-monospace,monospace")
      .attr("fill", (d) => getColors(d.type).stroke)
      .attr("pointer-events", "none")
      .text((d) => (d.type || "").toUpperCase());

    /* ── Force simulation ── */
    const sim = d3.forceSimulation<SimNode>(simNodes)
      .force("link",
        d3.forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(130)
          .strength(0.35)
      )
      .force("charge",  d3.forceManyBody<SimNode>().strength(-500).distanceMax(500))
      .force("center",  d3.forceCenter<SimNode>(w / 2, h / 2).strength(0.06))
      .force("collide", d3.forceCollide<SimNode>(NODE_RADIUS + 18))
      .force("radial",  d3.forceRadial<SimNode>(Math.min(w, h) * 0.30, w / 2, h / 2).strength(0.035))
      .alphaDecay(0.022)
      .on("tick", () => {
        // update link paths (curved arc)
        linkSel.attr("d", (d) => {
          const s = d.source as SimNode;
          const t = d.target as SimNode;
          const sx = s.x ?? 0, sy = s.y ?? 0;
          const tx = t.x ?? 0, ty = t.y ?? 0;
          if (isNaN(sx) || isNaN(sy) || isNaN(tx) || isNaN(ty)) return "";
          const dx = tx - sx, dy = ty - sy;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist === 0) return `M${sx},${sy}L${tx},${ty}`;
          const dr = Math.max(1, dist * 0.55);
          return `M${sx},${sy}A${dr},${dr} 0 0,1 ${tx},${ty}`;
        });

        // update edge label positions
        edgeLabelSel
          .attr("x", (d) => (((d.source as SimNode).x ?? 0) + ((d.target as SimNode).x ?? 0)) / 2)
          .attr("y", (d) => (((d.source as SimNode).y ?? 0) + ((d.target as SimNode).y ?? 0)) / 2 - 8);

        // update node positions
        nodeSel.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
      });

    simRef.current = sim;

    return () => { sim.stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges, dims]);

  /* ── Highlight effect ── */
  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    svg.selectAll<SVGGElement, SimNode>("g.nd")
      .transition().duration(250)
      .style("opacity", (d) => (!highlightId || d.id === highlightId) ? 1 : 0.2);
    svg.selectAll<SVGPathElement, SimLink>("g.g-links path")
      .transition().duration(250)
      .style("opacity", (d) => {
        if (!highlightId) return 1;
        const src = typeof d.source === "string" ? d.source : (d.source as SimNode).id;
        const tgt = typeof d.target === "string" ? d.target : (d.target as SimNode).id;
        return (src === highlightId || tgt === highlightId) ? 1 : 0.06;
      });
  }, [highlightId]);

  return (
    <div ref={containerRef} className="w-full h-full relative overflow-hidden rounded-xl" style={{ background: "#020b18" }}>

      {/* ── Starfield (CSS background layer) ── */}
      <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 0 }}>
        <defs>
          <radialGradient id="cosmos-bg" cx="50%" cy="50%" r="65%">
            <stop offset="0%"   stopColor="#091526" />
            <stop offset="100%" stopColor="#020b18" />
          </radialGradient>
        </defs>
        <rect width="100%" height="100%" fill="url(#cosmos-bg)" />

        {STARS.map((s) => (
          <circle key={s.id} cx={`${s.cx}%`} cy={`${s.cy}%`} r={s.r} fill="white" opacity={s.o}>
            <animate
              attributeName="opacity"
              values={`${s.o};${(s.o * 0.25).toFixed(2)};${s.o}`}
              dur={`${s.dur}s`}
              repeatCount="indefinite"
            />
          </circle>
        ))}

        {/* Globe ring decorations */}
        <ellipse cx="50%" cy="50%" rx="34%" ry="9%"  fill="none" stroke="#1d4ed8" strokeWidth="0.8" opacity="0.18" />
        <ellipse cx="50%" cy="50%" rx="44%" ry="18%" fill="none" stroke="#1d4ed8" strokeWidth="0.5" opacity="0.10" />
        <circle  cx="50%" cy="50%" r="33%"            fill="none" stroke="#1d4ed8" strokeWidth="0.5"
          strokeDasharray="6 10" opacity="0.14" />
      </svg>

      {/* ── D3 graph canvas ── */}
      <svg
        ref={svgRef}
        className="absolute inset-0 w-full h-full"
        style={{ zIndex: 1 }}
      />

      {/* ── Node / Edge count badge ── */}
      <div className="absolute bottom-4 left-4 pointer-events-none" style={{ zIndex: 2 }}>
        <div className="bg-black/55 backdrop-blur border border-white/10 rounded-lg px-3 py-2 font-mono space-y-0.5">
          <p className="text-[10px]"><span className="text-blue-400">{nodes.length}</span> <span className="text-gray-500">entities</span></p>
          <p className="text-[10px]"><span className="text-emerald-400">{edges.length}</span> <span className="text-gray-500">relations</span></p>
        </div>
      </div>

      {/* ── Legend ── */}
      <div className="absolute bottom-4 right-4 pointer-events-none" style={{ zIndex: 2 }}>
        <div className="bg-black/55 backdrop-blur border border-white/10 rounded-xl px-3 py-3 space-y-1.5">
          <p className="text-[9px] text-gray-500 uppercase font-mono tracking-wider mb-2">Entity Types</p>
          {(["person","organization","project","goal","event","decision","role","concept","document","product"] as const).map((type) => {
            const c = getColors(type);
            return (
              <div key={type} className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ background: c.glow, boxShadow: `0 0 5px ${c.glow}60` }} />
                <span className="text-[9.5px] text-gray-400 font-mono capitalize">{type}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
