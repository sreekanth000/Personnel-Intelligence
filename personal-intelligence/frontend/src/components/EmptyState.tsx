import React from "react";
import { Database } from "lucide-react";

interface EmptyStateProps {
  title?: string;
  description?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = "No records found",
  description = "No matching personal state records exist in the Personal World Model.",
  icon,
  action,
}) => {
  return (
    <div className="w-full p-12 bg-gray-900/40 border border-gray-800 rounded-xl flex flex-col items-center justify-center text-center">
      <div className="p-3 bg-gray-800/60 border border-gray-700/60 rounded-xl text-gray-400 mb-4">
        {icon || <Database className="w-8 h-8 text-gray-400" />}
      </div>
      <h3 className="text-base font-semibold text-gray-200">{title}</h3>
      <p className="text-sm text-gray-400 max-w-md mt-1 mb-6">{description}</p>
      {action && <div>{action}</div>}
    </div>
  );
};
