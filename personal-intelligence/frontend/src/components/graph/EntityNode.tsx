import { Handle, Position } from "@xyflow/react";
import {
  Brain,
  Building2,
  Calendar,
  CheckCircle2,
  Compass,
  FileText,
  FolderGit2,
  User,
} from "lucide-react";

export interface EntityNodeData {
  id: string;
  type: string;
  label: string;
  metadata?: Record<string, unknown>;
}

export const EntityNode = ({
  data,
  selected,
}: {
  data: EntityNodeData;
  selected: boolean;
}) => {
  let Icon = Brain;
  let bgClass = "bg-gray-900 border-gray-700";
  let textClass = "text-gray-200";
  let iconClass = "text-gray-400";
  let shapeClass = "rounded-xl";

  switch (data.type) {
    case "person":
      Icon = User;
      bgClass = "bg-blue-950/40 border-blue-800/60";
      textClass = "text-blue-100";
      iconClass = "text-blue-400";
      shapeClass = "rounded-full px-4";
      break;
    case "organization":
      Icon = Building2;
      bgClass = "bg-indigo-950/40 border-indigo-800/60";
      textClass = "text-indigo-100";
      iconClass = "text-indigo-400";
      shapeClass = "rounded-lg";
      break;
    case "project":
      Icon = FolderGit2;
      bgClass = "bg-emerald-950/40 border-emerald-800/60";
      textClass = "text-emerald-100";
      iconClass = "text-emerald-400";
      shapeClass = "rounded-lg";
      break;
    case "goal":
      Icon = CheckCircle2;
      bgClass = "bg-amber-950/40 border-amber-800/60";
      textClass = "text-amber-100";
      iconClass = "text-amber-400";
      shapeClass = "rounded-lg";
      break;
    case "decision":
      Icon = Compass;
      bgClass = "bg-purple-950/40 border-purple-800/60";
      textClass = "text-purple-100";
      iconClass = "text-purple-400";
      shapeClass = "rounded-br-3xl rounded-tl-3xl";
      break;
    case "event":
      Icon = Calendar;
      bgClass = "bg-rose-950/40 border-rose-800/60";
      textClass = "text-rose-100";
      iconClass = "text-rose-400";
      shapeClass = "rounded-lg";
      break;
    case "document":
      Icon = FileText;
      bgClass = "bg-slate-800/60 border-slate-700/60";
      textClass = "text-slate-200";
      iconClass = "text-slate-400";
      shapeClass = "rounded-sm";
      break;
  }

  const selectedClass = selected
    ? "ring-2 ring-white/60 shadow-[0_0_15px_rgba(255,255,255,0.2)]"
    : "hover:border-gray-500 shadow-md";

  const confidenceScore = (data.metadata?.confidence as number) ?? 1.0;
  const isUncertain = confidenceScore < 0.7;

  return (
    <div
      className={`flex items-center space-x-2.5 px-3.5 py-2.5 border backdrop-blur-sm transition-all min-w-[120px] ${bgClass} ${shapeClass} ${selectedClass} ${
        isUncertain ? "border-dashed border-red-500/50" : ""
      }`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-1.5 h-1.5 bg-gray-500 border-none opacity-0 group-hover:opacity-100"
      />
      <Icon className={`w-4 h-4 flex-shrink-0 ${iconClass}`} />
      <div className="flex flex-col overflow-hidden">
        <span
          className={`text-[11px] font-bold tracking-wide truncate ${textClass}`}
        >
          {data.label}
        </span>
        <span className="text-[8px] uppercase tracking-widest text-gray-500 opacity-80 mt-0.5">
          {data.type}
        </span>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="w-1.5 h-1.5 bg-gray-500 border-none opacity-0 group-hover:opacity-100"
      />
    </div>
  );
};
