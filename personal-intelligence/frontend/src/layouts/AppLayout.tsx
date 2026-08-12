import React from "react";
import { Header } from "../components/Header";
import type { NavTab } from "../components/Sidebar";
import { Sidebar } from "../components/Sidebar";

interface AppLayoutProps {
  activeTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  onSearchOpen: () => void;
  children: React.ReactNode;
}

export const AppLayout: React.FC<AppLayoutProps> = ({
  activeTab,
  onTabChange,
  onSearchOpen,
  children,
}) => {
  const isFullBleed = activeTab === "graph";

  return (
    <div className="h-screen bg-gray-950 text-gray-100 flex flex-col selection:bg-purple-500 selection:text-white overflow-hidden">
      <Header />
      <div className="flex flex-1 overflow-hidden min-h-0">
        <Sidebar
          activeTab={activeTab}
          onTabChange={onTabChange}
          onSearchOpen={onSearchOpen}
        />
        <main
          className={
            isFullBleed
              ? "flex-1 overflow-hidden p-4 bg-gray-950/60 min-h-0"
              : "flex-1 overflow-y-auto p-6 md:p-8 bg-gray-950/60 max-w-7xl mx-auto w-full space-y-6"
          }
        >
          {children}
        </main>
      </div>
    </div>
  );
};
