import { BaseEdge, getBezierPath } from "@xyflow/react";
import type { EdgeProps } from "@xyflow/react";

export const RelationshipEdge = ({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  label,
  selected,
  data,
}: EdgeProps) => {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const confidenceScore = (data?.confidence as number) ?? 1.0;
  const isUncertain = confidenceScore < 0.7 || data?.status === "uncertain";

  const edgeColor = selected
    ? "#c084fc" // purple-400
    : isUncertain
      ? "#ef4444" // red-500
      : "#4b5563"; // gray-600

  const edgeStyle = {
    ...style,
    strokeWidth: selected ? 2 : 1,
    stroke: edgeColor,
    strokeDasharray: isUncertain ? "5,5" : "none",
  };

  return (
    <>
      <BaseEdge path={edgePath} markerEnd={markerEnd} style={edgeStyle} />

      {/* Invisible thicker edge for easier clicking */}
      <BaseEdge
        path={edgePath}
        style={{ strokeWidth: 20, stroke: "transparent", cursor: "pointer" }}
      />

      {label && (
        <div
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: "all",
          }}
          className="nodrag nopan"
        >
          <div
            className={`px-2 py-0.5 rounded text-[9px] font-bold tracking-wider uppercase border transition-colors ${
              selected
                ? "bg-purple-950/80 text-purple-300 border-purple-800 shadow-[0_0_10px_rgba(192,132,252,0.3)]"
                : isUncertain
                  ? "bg-red-950/80 text-red-300 border-red-800/60"
                  : "bg-gray-950/80 text-gray-400 border-gray-800"
            }`}
          >
            {label}
          </div>
        </div>
      )}
    </>
  );
};
