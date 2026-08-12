/**
 * Utility functions for date formatting, badge colors, and text truncation.
 */

export function formatDate(dateString?: string): string {
  if (!dateString) return "N/A";
  try {
    const d = new Date(dateString);
    if (isNaN(d.getTime())) return dateString;
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateString;
  }
}

export function formatConfidence(score?: number): string {
  if (score === undefined || score === null) return "0%";
  return `${Math.round(score * 100)}%`;
}

export function getOutcomeBadgeColor(outcome?: string): string {
  switch (outcome?.toUpperCase()) {
    case "NOVEL":
      return "bg-blue-900/50 text-blue-300 border-blue-700/50";
    case "CONFIRM":
      return "bg-emerald-900/50 text-emerald-300 border-emerald-700/50";
    case "REFINE":
      return "bg-cyan-900/50 text-cyan-300 border-cyan-700/50";
    case "UPDATE":
      return "bg-purple-900/50 text-purple-300 border-purple-700/50";
    case "CONFLICT":
      return "bg-red-900/50 text-red-300 border-red-700/50";
    case "UNCERTAIN":
      return "bg-amber-900/50 text-amber-300 border-amber-700/50";
    default:
      return "bg-gray-800 text-gray-300 border-gray-700";
  }
}

export function getEntityTypeColor(type?: string): string {
  switch (type?.toLowerCase()) {
    case "person":
      return "bg-blue-950 text-blue-400 border-blue-800/60";
    case "organization":
      return "bg-indigo-950 text-indigo-400 border-indigo-800/60";
    case "project":
      return "bg-emerald-950 text-emerald-400 border-emerald-800/60";
    case "decision":
      return "bg-amber-950 text-amber-400 border-amber-800/60";
    case "goal":
      return "bg-purple-950 text-purple-400 border-purple-800/60";
    default:
      return "bg-gray-900 text-gray-400 border-gray-800";
  }
}

export function truncateText(text?: string, maxLength: number = 100): string {
  if (!text) return "";
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...`;
}
