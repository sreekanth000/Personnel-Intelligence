import React, { useState, useEffect } from "react";
import type { NavTab } from "./components/Sidebar";
import { AppLayout } from "./layouts/AppLayout";
import { DecisionsPage } from "./pages/DecisionsPage";
import { EmailsPage } from "./pages/EmailsPage";
import { EntitiesPage } from "./pages/EntitiesPage";
import { EvidencePage } from "./pages/EvidencePage";
import { OverviewPage } from "./pages/OverviewPage";
import { TimelinePage } from "./pages/TimelinePage";
import { WorldGraphPage } from "./pages/WorldGraphPage";
import { ExtractionQualityPage } from "./pages/ExtractionQualityPage";
import { MyWorldPage } from "./pages/MyWorldPage";
import { PrivacyPage } from "./pages/PrivacyPage";
import { GlobalSearchPalette } from "./components/search/GlobalSearchPalette";

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NavTab>("my_world");
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handleNavigate = (tab: string, id?: string) => {
    setActiveTab(tab as NavTab);

    if (id) {
      setTimeout(() => {
        window.dispatchEvent(
          new CustomEvent("deeplink", { detail: { tab, id } }),
        );
      }, 100);
    }
  };

  const renderContent = () => {
    switch (activeTab) {
      case "my_world":
        return <MyWorldPage />;
      case "overview":
        return (
          <OverviewPage onNavigate={(tab) => handleNavigate(tab as string)} />
        );
      case "emails":
        return <EmailsPage />;
      case "entities":
        return <EntitiesPage />;
      case "graph":
        return <WorldGraphPage />;
      case "timeline":
        return <TimelinePage />;
      case "evidence":
        return <EvidencePage />;
      case "decisions":
        return <DecisionsPage />;
      case "extraction_quality":
        return <ExtractionQualityPage />;
      case "privacy":
        return <PrivacyPage />;
      default:
        return <OverviewPage />;
    }
  };

  return (
    <>
      <AppLayout
        activeTab={activeTab}
        onTabChange={(tab) => handleNavigate(tab as string)}
        onSearchOpen={() => setSearchOpen(true)}
      >
        {renderContent()}
      </AppLayout>
      <GlobalSearchPalette
        isOpen={searchOpen}
        onClose={() => setSearchOpen(false)}
        onNavigate={handleNavigate}
      />
    </>
  );
};

export default App;
