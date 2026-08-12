import { AlertCircle, Clock, GitCommit, ShieldCheck } from "lucide-react";
import React, { useEffect, useRef } from "react";
import type { StateChange } from "../../types";
import { getOutcomeBadgeColor } from "../../utils/formatters";

interface TimelinePanelProps {
  changes: StateChange[];
  selectedEventId: string | null;
  onSelectEvent: (change: StateChange) => void;
  highlightEntityId: string | null;
}

export const TimelinePanel: React.FC<TimelinePanelProps> = ({
  changes,
  selectedEventId,
  onSelectEvent,
  highlightEntityId,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const highlightedRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // Auto-scroll to highlighted entity's first event
  useEffect(() => {
    if (highlightEntityId) {
      // Find the first change related to this entity
      const relatedChange = changes.find(
        (c) =>
          c.entity_id === highlightEntityId ||
          c.description.includes(highlightEntityId),
      );
      if (relatedChange && highlightedRefs.current[relatedChange.id]) {
        highlightedRefs.current[relatedChange.id]?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }
    }
  }, [highlightEntityId, changes]);

  if (changes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-500 p-6 text-center space-y-3">
        <p className="text-sm font-semibold text-gray-400">
          No Timeline Events
        </p>
        <p className="text-xs mt-1">State updates will appear here.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-gray-900 border-r border-gray-800">
      <div className="p-4 border-b border-gray-800 shrink-0">
        <h3 className="text-sm font-bold text-white">Timeline</h3>
        <p className="text-[10px] text-gray-500 mt-0.5">
          Chronological audit trail
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-4" ref={containerRef}>
        <div className="relative pl-5 border-l border-gray-800 space-y-3">
          {changes.map((c) => {
            const isSelected = selectedEventId === c.id;
            const isRelated =
              highlightEntityId &&
              (c.entity_id === highlightEntityId ||
                c.description.includes(highlightEntityId));

            return (
              <div
                key={c.id}
                className="relative group"
                ref={(el) => {
                  highlightedRefs.current[c.id] = el;
                }}
              >
                <div
                  className={`absolute -left-[25px] top-1.5 p-0.5 border-2 rounded-full transition-colors ${isSelected || isRelated ? "bg-blue-900 border-blue-500 text-blue-200 shadow-[0_0_8px_rgba(59,130,246,0.5)]" : "bg-gray-950 border-gray-700 text-blue-400 group-hover:border-blue-500"}`}
                >
                  <GitCommit className="w-2.5 h-2.5" />
                </div>

                <button
                  onClick={() => onSelectEvent(c)}
                  className={`w-full text-left p-2.5 border rounded-xl space-y-2 transition-colors cursor-pointer ${
                    isSelected
                      ? "bg-gray-800 border-gray-600 shadow-md"
                      : isRelated
                        ? "bg-blue-950/20 border-blue-900/50 hover:bg-blue-950/40"
                        : "bg-gray-900/60 hover:bg-gray-900 border-gray-800/60"
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <span
                      className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border mb-1 inline-block ${getOutcomeBadgeColor(c.outcome)}`}
                    >
                      {c.outcome}
                    </span>
                    <span className="text-[9px] text-gray-500 font-mono flex items-center space-x-1 shrink-0">
                      <Clock className="w-2.5 h-2.5 text-gray-400" />
                      <span>
                        {new Date(c.changed_at).toLocaleDateString([], {
                          month: "short",
                          day: "numeric",
                        })}
                      </span>
                    </span>
                  </div>

                  <h4 className="text-[11px] font-semibold text-gray-200 line-clamp-2 leading-snug">
                    {c.description}
                  </h4>

                  <div className="flex items-center justify-between text-[9px] text-gray-400 pt-1.5 border-t border-gray-800/60">
                    <span className="font-mono text-gray-500 truncate mr-1">
                      {c.observation_id.substring(0, 10)}...
                    </span>

                    {c.requires_review ? (
                      <span className="flex items-center space-x-1 text-amber-400 font-medium shrink-0">
                        <AlertCircle className="w-2.5 h-2.5" />
                        <span>Review</span>
                      </span>
                    ) : (
                      <span className="flex items-center space-x-1 text-emerald-400 font-medium shrink-0">
                        <ShieldCheck className="w-2.5 h-2.5" />
                        <span>Reconciled</span>
                      </span>
                    )}
                  </div>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
