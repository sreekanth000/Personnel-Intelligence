import React from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import {
  ShieldCheck,
  BrainCircuit,
  AlertTriangle,
  HelpCircle,
  History,
} from "lucide-react";
import { formatConfidence } from "../../utils/formatters";

export const IntelligenceEntityNode: React.FC<NodeProps> = ({
  data,
  selected,
}) => {
  const label = data.label as string;
  const state = data.epistemic_state as string;
  const confidence = data.confidence as number;
  const isHistorical = state === "HISTORICAL";

  // Determine styling based on epistemic state
  let borderClass = "border-gray-700 hover:border-gray-500";
  let bgClass = "bg-gray-950/80";
  let textClass = "text-gray-200";
  let icon = <BrainCircuit className="w-3.5 h-3.5 text-gray-400" />;
  let stateLabel = "INFERRED";
  let stateColor = "text-gray-400";

  switch (state) {
    case "OBSERVED":
      borderClass = "border-blue-500/50 hover:border-blue-400";
      icon = <BrainCircuit className="w-3.5 h-3.5 text-blue-400" />;
      stateLabel = "OBSERVED";
      stateColor = "text-blue-400";
      break;
    case "USER_CONFIRMED":
      borderClass = "border-emerald-500 hover:border-emerald-400";
      bgClass = "bg-emerald-950/20";
      icon = <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />;
      stateLabel = "CONFIRMED";
      stateColor = "text-emerald-400";
      break;
    case "CONFLICTING":
      borderClass = "border-red-500 shadow-[0_0_15px_rgba(239,68,68,0.2)]";
      bgClass = "bg-red-950/40";
      icon = <AlertTriangle className="w-3.5 h-3.5 text-red-400" />;
      stateLabel = "CONFLICT";
      stateColor = "text-red-400";
      break;
    case "UNCERTAIN":
      borderClass = "border-amber-500/50 border-dashed hover:border-amber-400";
      icon = <HelpCircle className="w-3.5 h-3.5 text-amber-400" />;
      stateLabel = "UNCERTAIN";
      stateColor = "text-amber-400";
      break;
    case "HISTORICAL":
      borderClass = "border-gray-800";
      bgClass = "bg-transparent";
      textClass = "text-gray-600";
      icon = <History className="w-3.5 h-3.5 text-gray-600" />;
      stateLabel = "HISTORICAL";
      stateColor = "text-gray-600";
      break;
  }

  if (selected) {
    borderClass = borderClass.replace("border-gray-700", "border-white");
    borderClass = borderClass.replace(
      "border-blue-500/50",
      "border-blue-400 shadow-[0_0_15px_rgba(59,130,246,0.5)]",
    );
  }

  return (
    <div
      className={`relative px-4 py-3 rounded-xl border backdrop-blur-sm transition-all shadow-lg ${borderClass} ${bgClass} ${isHistorical ? "opacity-50 grayscale" : ""} min-w-[200px]`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-gray-600 !border-gray-900"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-gray-600 !border-gray-900"
      />

      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0 pr-3">
          <h3 className={`font-semibold text-sm truncate ${textClass}`}>
            {label}
          </h3>
          <div className="flex items-center space-x-2 mt-1.5">
            {icon}
            <span
              className={`text-[9px] font-bold uppercase tracking-wider ${stateColor}`}
            >
              {stateLabel}
            </span>
          </div>
        </div>

        {confidence !== undefined && (
          <div className="shrink-0 flex items-center justify-center bg-gray-900 border border-gray-800 rounded px-1.5 py-0.5">
            <span className="text-[9px] font-mono font-bold text-gray-400">
              {formatConfidence(confidence)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};
