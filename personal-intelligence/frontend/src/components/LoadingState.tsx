import React from "react";

interface LoadingStateProps {
  message?: string;
  rows?: number;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  message = "Loading cognitive state...",
  rows = 3,
}) => {
  return (
    <div className="w-full p-6 bg-gray-900/60 border border-gray-800 rounded-xl space-y-4 animate-pulse">
      <div className="flex items-center space-x-3">
        <div className="w-5 h-5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
        <span className="text-sm font-medium text-gray-300">{message}</span>
      </div>

      <div className="space-y-3 pt-2">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="h-12 bg-gray-800/60 rounded-lg w-full" />
        ))}
      </div>
    </div>
  );
};
