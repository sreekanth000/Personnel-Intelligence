import React from "react";
import {
  Building2,
  Calendar,
  FileCode,
  FolderGit2,
  ShieldCheck,
  User,
} from "lucide-react";
import type { Entity } from "../types";
import {
  formatConfidence,
  formatDate,
  getEntityTypeColor,
} from "../utils/formatters";

interface EntityCardProps {
  entity: Entity;
  onSelect?: (entity: Entity) => void;
}

export const EntityCard: React.FC<EntityCardProps> = ({ entity, onSelect }) => {
  const getIcon = () => {
    switch (entity.entity_type) {
      case "person":
        return <User className="w-4 h-4 text-blue-400" />;
      case "organization":
        return <Building2 className="w-4 h-4 text-indigo-400" />;
      case "project":
        return <FolderGit2 className="w-4 h-4 text-emerald-400" />;
      case "decision":
        return <FileCode className="w-4 h-4 text-amber-400" />;
      default:
        return <Calendar className="w-4 h-4 text-purple-400" />;
    }
  };

  return (
    <div
      onClick={() => onSelect?.(entity)}
      className="p-4 bg-gray-900/60 hover:bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-xl transition-all space-y-3 cursor-pointer group"
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center space-x-2.5">
          <div className="p-2 bg-gray-800 border border-gray-700/60 rounded-lg group-hover:scale-105 transition-transform">
            {getIcon()}
          </div>
          <div>
            <h4 className="text-sm font-semibold text-gray-100 group-hover:text-blue-400 transition-colors">
              {entity.name}
            </h4>
            {entity.email && (
              <p className="text-xs text-gray-400 font-mono">{entity.email}</p>
            )}
            {entity.domain && (
              <p className="text-xs text-gray-400 font-mono">{entity.domain}</p>
            )}
          </div>
        </div>

        <span
          className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border ${getEntityTypeColor(
            entity.entity_type,
          )}`}
        >
          {entity.entity_type}
        </span>
      </div>

      {entity.aliases && entity.aliases.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          <span className="text-[11px] text-gray-500">Aliases:</span>
          {entity.aliases.map((alias, i) => (
            <span
              key={i}
              className="text-[10px] bg-gray-800/60 text-gray-400 px-1.5 py-0.5 rounded"
            >
              {alias}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between text-[11px] text-gray-500 pt-2 border-t border-gray-800/60">
        <span className="flex items-center space-x-1">
          <ShieldCheck className="w-3 h-3 text-emerald-400" />
          <span>Confidence: {formatConfidence(entity.confidence?.score)}</span>
        </span>
        <span>{formatDate(entity.created_at)}</span>
      </div>
    </div>
  );
};
