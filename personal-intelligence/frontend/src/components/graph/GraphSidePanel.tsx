import { CheckCircle2 } from "lucide-react";
import React from "react";
import type { UIGraphEdge, UIGraphNode } from "../../types";
import { formatConfidence, getEntityTypeColor } from "../../utils/formatters";
import { RelationshipInspector } from "../relationship/RelationshipInspector";

interface GraphSidePanelProps {
  selectedNode: UIGraphNode | null;
  selectedEdge: UIGraphEdge | null;
  nodeMap: Record<string, UIGraphNode>;
}

export const GraphSidePanel: React.FC<GraphSidePanelProps> = ({
  selectedNode,
  selectedEdge,
}) => {
  if (!selectedNode && !selectedEdge) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-500 p-6 text-center space-y-3">
        <div className="w-12 h-12 bg-gray-900 rounded-xl flex items-center justify-center">
          <svg
            className="w-6 h-6 text-gray-700"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-400">No Selection</p>
          <p className="text-xs mt-1">
            Select a node or edge in the graph to view details.
          </p>
        </div>
      </div>
    );
  }

  if (selectedNode) {
    const confidenceScore =
      (selectedNode.metadata?.confidence as number) ?? 1.0;

    return (
      <div className="p-5 space-y-6">
        <div>
          <div className="flex items-center space-x-2.5 mb-1">
            <h3 className="text-lg font-bold text-white tracking-tight">
              {selectedNode.label}
            </h3>
            <span
              className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${getEntityTypeColor(
                selectedNode.type as any,
              )}`}
            >
              {selectedNode.type}
            </span>
          </div>
          <p className="text-[10px] text-gray-500 font-mono">
            ID: {selectedNode.id}
          </p>
        </div>

        <div className="space-y-3">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
            Metadata Attributes
          </h4>
          <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-3 space-y-3 text-xs">
            {!!selectedNode.metadata?.email && (
              <div>
                <span className="text-gray-500 font-mono text-[10px] block mb-0.5">
                  Email
                </span>
                <span className="text-blue-400 font-mono">
                  {selectedNode.metadata.email as string}
                </span>
              </div>
            )}
            {!!selectedNode.metadata?.domain && (
              <div>
                <span className="text-gray-500 font-mono text-[10px] block mb-0.5">
                  Domain
                </span>
                <span className="text-indigo-300 font-mono">
                  {selectedNode.metadata.domain as string}
                </span>
              </div>
            )}

            <div>
              <span className="text-gray-500 font-mono text-[10px] block mb-0.5">
                Confidence
              </span>
              <span className="text-emerald-400 font-semibold font-mono flex items-center space-x-1.5 mt-1">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>{formatConfidence(confidenceScore)}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (selectedEdge) {
    return (
      <RelationshipInspector
        relationshipId={selectedEdge.id}
        onViewEvidence={(id) => console.log("View evidence", id)}
      />
    );
  }

  return null;
};
