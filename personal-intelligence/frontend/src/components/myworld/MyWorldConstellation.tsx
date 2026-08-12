/**
 * MyWorldConstellation — Interactive force-directed galaxy visualization for My World Canvas.
 * Categories form glowing orbital hubs (People, Organizations, Projects, Goals, Decisions).
 */
import * as d3 from "d3";
import React, { useEffect, useRef, useState } from "react";
import type { MyWorldEdge, MyWorldNode } from "../../api/myworld";

const CATEGORY_CONFIG: Record<
  string,
  { label: string; color: string; fill: string; border: string; glow: string; icon: string }
> = {
  people: {
    label: "Key People",
    color: "#3b82f6",
    fill: "#1e3a5f",
    border: "#60a5fa",
    glow: "rgba(59, 130, 246, 0.4)",
    icon: "👤",
  },
  organizations: {
    label: "Organizations",
    color: "#818cf8",
    fill: "#1e1a3f",
    border: "#a5b4fc",
    glow: "rgba(129, 140, 248, 0.4)",
    icon: "🏢",
  },
  projects: {
    label: "Active Projects",
    color: "#10b981",
    fill: "#064e3b",
    border: "#34d399",
    glow: "rgba(16, 185, 129, 0.4)",
    icon: "🚀",
  },
  goals: {
    label: "Goals & Objectives",
    color: "#a855f7",
    fill: "#4c1d95",
    border: "#c084fc",
    glow: "rgba(168, 85, 247, 0.4)",
    icon: "🎯",
  },
  decisions: {
    label: "Decisions",
    color: "#f97316",
    fill: "#431407",
    border: "#fb923c",
    glow: "rgba(249, 115, 22, 0.4)",
    icon: "⚖️",
  },
};

const getCategoryCfg = (cat: string) =>
  CATEGORY_CONFIG[cat?.toLowerCase()] ?? {
    label: cat,
    color: "#6b7280",
    fill: "#1f2937",
    border: "#9ca3af",
    glow: "rgba(107, 114, 128, 0.3)",
    icon: "📌",
  };

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  label: string;
  category: string;
  epistemic_state: string;
  confidence: number;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  id: string;
  label: string;
  epistemic_state: string;
  confidence: number;
}

interface Props {
  nodes: MyWorldNode[];
  edges: MyWorldEdge[];
  onSelectNode: (node: MyWorldNode) => void;
  selectedNodeId: string | null;
  searchQuery: string;
  selectedCategory: string;
}

export const MyWorldConstellation: React.FC<Props> = ({
  nodes,
  edges,
  onSelectNode,
  selectedNodeId,
  searchQuery,
  selectedCategory,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);

  const [dims, setDims] = useState({ w: 1200, h: 800 });

  const onSelectRef = useRef(onSelectNode);
  useEffect(() => {
    onSelectRef.current = onSelectNode;
  }, [onSelectNode]);

  // Dimension tracking
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      if (r.width > 0) setDims({ w: r.width, h: r.height });
    });
    ro.observe(el);
    const rect = el.getBoundingClientRect();
    if (rect.width > 0) setDims({ w: rect.width, h: rect.height });
    return () => ro.disconnect();
  }, []);

  // Simulation setup
  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    const { w, h } = dims;

    simRef.current?.stop();

    // Filter nodes based on category / search
    let filteredNodes = nodes;
    if (selectedCategory !== "all") {
      filteredNodes = filteredNodes.filter((n) => n.category === selectedCategory);
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filteredNodes = filteredNodes.filter((n) => (n.label || "").toLowerCase().includes(q));
    }

    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredEdges = edges.filter(
      (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
    );

    // Group center positions for categories
    const categories = ["people", "organizations", "projects", "goals", "decisions"];
    const categoryCenters: Record<string, { x: number; y: number }> = {};
    const radius = Math.min(w, h) * 0.32;
    categories.forEach((cat, idx) => {
      const angle = (idx / categories.length) * 2 * Math.PI - Math.PI / 2;
      categoryCenters[cat] = {
        x: w / 2 + Math.cos(angle) * radius,
        y: h / 2 + Math.sin(angle) * radius,
      };
    });

    const simNodes: SimNode[] = filteredNodes.map((n, i) => {
      const center = categoryCenters[n.category] ?? { x: w / 2, y: h / 2 };
      return {
        ...n,
        x: center.x + (Math.random() - 0.5) * 120,
        y: center.y + (Math.random() - 0.5) * 120,
      };
    });

    const simLinks: SimLink[] = filteredEdges.map((e) => ({
      ...e,
      source: e.source,
      target: e.target,
    }));

    svg.selectAll(".g-root").remove();

    // Defs & Filters
    let defs = svg.select<SVGDefsElement>("defs");
    if (defs.empty()) defs = svg.append("defs");
    defs.html("");

    const glow = defs
      .append("filter")
      .attr("id", "mw-node-glow")
      .attr("x", "-50%")
      .attr("y", "-50%")
      .attr("width", "200%")
      .attr("height", "200%");
    glow.append("feGaussianBlur").attr("in", "SourceGraphic").attr("stdDeviation", "4").attr("result", "blur");
    const m = glow.append("feMerge");
    m.append("feMergeNode").attr("in", "blur");
    m.append("feMergeNode").attr("in", "SourceGraphic");

    const root = svg.append("g").attr("class", "g-root");

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 4])
      .on("zoom", (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) => {
        root.attr("transform", event.transform.toString());
      });

    svg.call(zoom).on("dblclick.zoom", null);

    // Draw Category Orbit Rings
    const orbitGroup = root.append("g").attr("class", "g-orbits");
    Object.entries(categoryCenters).forEach(([cat, center]) => {
      const cfg = getCategoryCfg(cat);

      // Orbit circle
      orbitGroup
        .append("circle")
        .attr("cx", center.x)
        .attr("cy", center.y)
        .attr("r", 150)
        .attr("fill", cfg.fill + "18")
        .attr("stroke", cfg.border + "30")
        .attr("stroke-width", 1.5)
        .attr("stroke-dasharray", "4 6");

      // Orbit header pill
      const header = orbitGroup
        .append("g")
        .attr("transform", `translate(${center.x}, ${center.y - 165})`);

      header
        .append("rect")
        .attr("x", -70)
        .attr("y", -14)
        .attr("width", 140)
        .attr("height", 28)
        .attr("rx", 14)
        .attr("fill", "#091322e6")
        .attr("stroke", cfg.border + "80")
        .attr("stroke-width", 1.5);

      header
        .append("text")
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "middle")
        .attr("font-size", "10")
        .attr("font-weight", "700")
        .attr("font-family", "ui-monospace, monospace")
        .attr("fill", cfg.border)
        .text(`${cfg.icon} ${cfg.label.toUpperCase()}`);
    });

    // Link layer
    const linkSel = root
      .append("g")
      .attr("class", "g-links")
      .selectAll<SVGPathElement, SimLink>("path")
      .data(simLinks, (d) => d.id)
      .enter()
      .append("path")
      .attr("fill", "none")
      .attr("stroke", (d) =>
        d.epistemic_state === "CONFLICTING"
          ? "#ef4444"
          : d.epistemic_state === "UNCERTAIN"
          ? "#f59e0b"
          : "#3b82f640"
      )
      .attr("stroke-width", (d) => (d.epistemic_state === "CONFLICTING" ? 2.5 : 1.5))
      .attr("stroke-dasharray", (d) => (d.epistemic_state === "UNCERTAIN" ? "4 4" : "none"));

    // Node layer
    const nodeSel = root
      .append("g")
      .attr("class", "g-nodes")
      .selectAll<SVGGElement, SimNode>("g.mw-nd")
      .data(simNodes, (d) => d.id)
      .enter()
      .append("g")
      .attr("class", "mw-nd")
      .style("cursor", "pointer")
      .on("click", (_e, d) => {
        const orig = nodes.find((n) => n.id === d.id);
        if (orig) onSelectRef.current(orig);
      })
      .call(
        d3
          .drag<SVGGElement, SimNode>()
          .on("start", (e, d) => {
            if (!e.active) simRef.current?.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (e, d) => {
            d.fx = e.x;
            d.fy = e.y;
          })
          .on("end", (e, d) => {
            if (!e.active) simRef.current?.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    // Node card background
    nodeSel
      .append("rect")
      .attr("x", -70)
      .attr("y", -20)
      .attr("width", 140)
      .attr("height", 40)
      .attr("rx", 10)
      .attr("fill", (d) => getCategoryCfg(d.category).fill)
      .attr("stroke", (d) =>
        d.epistemic_state === "CONFLICTING"
          ? "#ef4444"
          : d.epistemic_state === "USER_CONFIRMED"
          ? "#10b981"
          : d.epistemic_state === "UNCERTAIN"
          ? "#f59e0b"
          : getCategoryCfg(d.category).border
      )
      .attr("stroke-width", (d) => (d.epistemic_state === "USER_CONFIRMED" ? 2 : 1.5))
      .attr("filter", "url(#mw-node-glow)");

    // Node label
    nodeSel
      .append("text")
      .attr("x", 0)
      .attr("y", -3)
      .attr("text-anchor", "middle")
      .attr("font-size", "10")
      .attr("font-weight", "600")
      .attr("font-family", "Inter, sans-serif")
      .attr("fill", "#f3f4f6")
      .attr("pointer-events", "none")
      .text((d) => (d.label.length > 18 ? d.label.slice(0, 16) + "…" : d.label));

    // Epistemic state pill
    nodeSel
      .append("text")
      .attr("x", 0)
      .attr("y", 12)
      .attr("text-anchor", "middle")
      .attr("font-size", "7.5")
      .attr("font-weight", "700")
      .attr("font-family", "ui-monospace, monospace")
      .attr("fill", (d) =>
        d.epistemic_state === "CONFLICTING"
          ? "#f87171"
          : d.epistemic_state === "USER_CONFIRMED"
          ? "#34d399"
          : d.epistemic_state === "UNCERTAIN"
          ? "#fbbf24"
          : getCategoryCfg(d.category).border
      )
      .attr("pointer-events", "none")
      .text((d) => d.epistemic_state);

    // Simulation forces
    const sim = d3
      .forceSimulation<SimNode>(simNodes)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(100)
          .strength(0.2)
      )
      .force(
        "category",
        d3
          .forceX<SimNode>()
          .x((d) => categoryCenters[d.category]?.x ?? w / 2)
          .strength(0.4)
      )
      .force(
        "categoryY",
        d3
          .forceY<SimNode>()
          .y((d) => categoryCenters[d.category]?.y ?? h / 2)
          .strength(0.4)
      )
      .force("charge", d3.forceManyBody<SimNode>().strength(-180))
      .force("collide", d3.forceCollide<SimNode>(50))
      .alphaDecay(0.025)
      .on("tick", () => {
        linkSel.attr("d", (d) => {
          const s = d.source as SimNode;
          const t = d.target as SimNode;
          const sx = s.x ?? 0,
            sy = s.y ?? 0,
            tx = t.x ?? 0,
            ty = t.y ?? 0;
          if (isNaN(sx) || isNaN(sy) || isNaN(tx) || isNaN(ty)) return "";
          return `M${sx},${sy}L${tx},${ty}`;
        });

        nodeSel.attr("transform", (d) => `translate(${d.x ?? 0}, ${d.y ?? 0})`);
      });

    simRef.current = sim;

    return () => {
      sim.stop();
    };
  }, [nodes, edges, dims, selectedCategory, searchQuery]);

  // Selection highlight
  useEffect(() => {
    const svg = d3.select(svgRef.current!);
    svg
      .selectAll<SVGGElement, SimNode>("g.mw-nd")
      .transition()
      .duration(200)
      .style("opacity", (d) => (!selectedNodeId || d.id === selectedNodeId ? 1 : 0.25));
  }, [selectedNodeId]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full relative overflow-hidden rounded-2xl border border-white/10"
      style={{ background: "#030814" }}
    >
      <svg ref={svgRef} className="w-full h-full absolute inset-0" />
    </div>
  );
};
