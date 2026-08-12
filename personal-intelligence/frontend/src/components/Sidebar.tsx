import React from "react";
import {
  Clock,
  Compass,
  FileCheck,
  GitFork,
  Globe,
  LayoutDashboard,
  Mail,
  Users,
  ActivitySquare,
  Search,
  ShieldAlert,
} from "lucide-react";

export type NavTab =
  | "my_world"
  | "overview"
  | "emails"
  | "entities"
  | "graph"
  | "timeline"
  | "evidence"
  | "decisions"
  | "extraction_quality"
  | "privacy";

interface SidebarProps {
  activeTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  onSearchOpen: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onTabChange,
  onSearchOpen,
}) => {
  const navItems: { id: NavTab; label: string; icon: React.ReactNode }[] = [
    {
      id: "my_world",
      label: "My World",
      icon: <GitFork className="w-4 h-4" />,
    },
    {
      id: "overview",
      label: "Dashboard",
      icon: <LayoutDashboard className="w-4 h-4" />,
    },
    {
      id: "emails",
      label: "Emails",
      icon: <Mail className="w-4 h-4" />,
    },
    {
      id: "entities",
      label: "Entities",
      icon: <Users className="w-4 h-4" />,
    },
    {
      id: "graph",
      label: "World Graph",
      icon: <Globe className="w-4 h-4" />,
    },
    {
      id: "timeline",
      label: "Timeline",
      icon: <Clock className="w-4 h-4" />,
    },
    {
      id: "evidence",
      label: "Evidence",
      icon: <FileCheck className="w-4 h-4" />,
    },
    {
      id: "decisions",
      label: "Decisions",
      icon: <Compass className="w-4 h-4" />,
    },
    {
      id: "extraction_quality",
      label: "Quality Ops",
      icon: <ActivitySquare className="w-4 h-4" />,
    },
    {
      id: "privacy",
      label: "Privacy & Data Flow",
      icon: <ShieldAlert className="w-4 h-4 text-red-400" />,
    },
  ];

  return (
    <aside className="w-64 border-r border-gray-800 bg-gray-950 flex flex-col justify-between shrink-0 min-h-[calc(100vh-4rem)]">
      <div className="p-4 space-y-1">
        <button
          onClick={onSearchOpen}
          className="w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all text-gray-400 hover:text-gray-200 hover:bg-gray-900/60 cursor-text mb-4 border border-gray-800"
        >
          <Search className="w-4 h-4 text-gray-500" />
          <span className="flex-1 text-left">Search...</span>
          <span className="text-[10px] font-mono text-gray-500 border border-gray-800 rounded px-1.5 py-0.5 bg-gray-950">
            Cmd K
          </span>
        </button>

        <div className="px-3 py-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
          Navigation
        </div>
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                isActive
                  ? "bg-gradient-to-r from-blue-600/20 to-purple-600/20 text-white border border-blue-500/40 shadow-sm"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-900/60"
              }`}
            >
              <span className={isActive ? "text-blue-400" : "text-gray-400"}>
                {item.icon}
              </span>
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      <div className="p-4 border-t border-gray-800 bg-gray-900/40">
        <div className="p-3 bg-gray-900 border border-gray-800 rounded-lg">
          <h4 className="text-xs font-medium text-gray-200">
            Local-First Guard
          </h4>
          <p className="text-[11px] text-gray-400 mt-1 leading-relaxed">
            Observations persist in local DuckDB & Kuzu. No data sent to third
            parties without explicit reasoning filter.
          </p>
        </div>
      </div>
    </aside>
  );
};
