import React from "react";
import type { NodeProps } from "@xyflow/react";

export const CategoryZoneNode: React.FC<NodeProps> = ({ data }) => {
  const label = data.label as string;
  const width = (data.width as number) || 400;
  const height = (data.height as number) || 600;

  return (
    <div
      className="rounded-3xl border border-gray-800 bg-gray-900/30 backdrop-blur-md flex flex-col relative overflow-hidden group"
      style={{ width, height }}
    >
      {/* Subtle top glow based on category */}
      <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-blue-500/50 to-transparent opacity-50 group-hover:opacity-100 transition-opacity" />

      <div className="p-6 border-b border-gray-800/50 flex items-center justify-between">
        <h2 className="text-xl font-bold tracking-widest uppercase text-gray-500 group-hover:text-gray-300 transition-colors font-mono">
          {label}
        </h2>
      </div>

      {/* We do NOT need handles for the zone itself, but React Flow requires valid node setup. 
          We just won't attach edges to the zone directly. */}
    </div>
  );
};
