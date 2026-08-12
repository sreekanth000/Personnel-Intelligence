import React from "react";
import { Brain, Database, Search, ShieldCheck, WifiOff } from "lucide-react";
import { useHealthCheck } from "../hooks/useWorldModel";

interface HeaderProps {
  onSearch?: (query: string) => void;
}

export const Header: React.FC<HeaderProps> = () => {
  const { connected } = useHealthCheck();

  return (
    <header className="h-16 border-b border-gray-800 bg-gray-950/80 backdrop-blur px-6 flex items-center justify-between sticky top-0 z-30">
      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-2.5">
          <div className="p-2 bg-gradient-to-tr from-blue-600 to-purple-600 rounded-lg shadow-lg shadow-blue-500/20 text-white">
            <Brain className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-base font-bold text-white tracking-tight flex items-center space-x-2">
              <span>Personal Intelligence</span>
              <span className="text-[10px] font-mono uppercase bg-blue-950 text-blue-400 border border-blue-800 px-1.5 py-0.5 rounded">
                V0 Monolith
              </span>
            </h1>
            <p className="text-xs text-gray-400">User-Owned Cognitive Layer</p>
          </div>
        </div>
      </div>

      <div className="flex items-center space-x-4">
        <div className="relative hidden md:block w-72">
          <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search personal state & entities..."
            className="w-full pl-9 pr-4 py-1.5 bg-gray-900 border border-gray-800 rounded-lg text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>

        <div className="flex items-center space-x-2 border-l border-gray-800 pl-4">
          <div className="flex items-center space-x-1.5 px-2.5 py-1 bg-gray-900 border border-gray-800 rounded-full text-xs">
            <Database className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-gray-300 font-mono text-[11px]">
              DuckDB + Kuzu
            </span>
          </div>

          <div
            className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${
              connected
                ? "bg-emerald-950/60 border-emerald-800/60 text-emerald-400"
                : "bg-red-950/60 border-red-800/60 text-red-400"
            }`}
          >
            {connected ? (
              <>
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>Backend Online</span>
              </>
            ) : (
              <>
                <WifiOff className="w-3.5 h-3.5" />
                <span>Offline</span>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
