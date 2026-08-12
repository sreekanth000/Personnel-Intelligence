import React, { useState, useEffect, useRef } from "react";
import {
  Search,
  Loader2,
  User,
  Mail,
  Folder,
  GitFork,
  Clock,
  FileCheck,
  Compass,
  Target,
} from "lucide-react";
import { searchApi, type UISearchResult } from "../../api/search";
import { formatConfidence, formatDate } from "../../utils/formatters";

interface GlobalSearchPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (tab: string, id: string) => void;
}

export const GlobalSearchPalette: React.FC<GlobalSearchPaletteProps> = ({
  isOpen,
  onClose,
  onNavigate,
}) => {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<UISearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setQuery("");
      setResults([]);
    }
  }, [isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        // The App component will handle opening it
      }
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    const fetchResults = async () => {
      if (!query.trim()) {
        setResults([]);
        return;
      }
      setLoading(true);
      try {
        const res = await searchApi.globalSearch(query);
        setResults(res);
      } catch (err) {
        console.error("Search failed", err);
      } finally {
        setLoading(false);
      }
    };

    const debounce = setTimeout(fetchResults, 300);
    return () => clearTimeout(debounce);
  }, [query]);

  const handleSelect = (res: UISearchResult) => {
    // Map result type to target tab
    let tab = "overview";
    if (res.result_type === "entity") tab = "entities";
    else if (res.result_type === "relationship") tab = "graph";
    else if (res.result_type === "email") tab = "emails";
    else if (res.result_type === "timeline_event") tab = "timeline";

    onNavigate(tab, res.id);
    onClose();
  };

  const getIcon = (type: string, subtype?: string) => {
    if (type === "email") return <Mail className="w-4 h-4 text-emerald-400" />;
    if (type === "relationship")
      return <GitFork className="w-4 h-4 text-purple-400" />;
    if (type === "timeline_event")
      return <Clock className="w-4 h-4 text-amber-400" />;

    if (subtype === "person") return <User className="w-4 h-4 text-blue-400" />;
    if (subtype === "project")
      return <Folder className="w-4 h-4 text-blue-400" />;
    if (subtype === "decision")
      return <Compass className="w-4 h-4 text-blue-400" />;
    if (subtype === "goal") return <Target className="w-4 h-4 text-blue-400" />;
    return <FileCheck className="w-4 h-4 text-gray-400" />;
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh] bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl bg-gray-950 border border-gray-800 rounded-xl shadow-2xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input */}
        <div className="flex items-center px-4 py-3 border-b border-gray-800">
          <Search className="w-5 h-5 text-gray-500" />
          <input
            ref={inputRef}
            type="text"
            className="flex-1 bg-transparent border-none text-white px-4 py-2 focus:outline-none placeholder-gray-600 font-mono text-sm"
            placeholder="Search people, projects, relationships..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {loading && (
            <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />
          )}
          <div className="text-[10px] text-gray-600 font-mono border border-gray-800 px-1.5 py-0.5 rounded bg-gray-900 ml-2">
            ESC
          </div>
        </div>

        {/* Results */}
        <div className="max-h-[60vh] overflow-y-auto">
          {query.trim() && results.length === 0 && !loading && (
            <div className="p-8 text-center text-gray-500 text-sm">
              No results found for "{query}"
            </div>
          )}

          {results.length > 0 && (
            <div className="py-2">
              {results.map((res) => (
                <button
                  key={`${res.result_type}_${res.id}`}
                  onClick={() => handleSelect(res)}
                  className="w-full flex items-start px-4 py-3 hover:bg-gray-800/50 transition-colors text-left border-l-2 border-transparent hover:border-blue-500 group"
                >
                  <div className="mt-0.5 mr-3 p-1.5 bg-gray-900 rounded-md border border-gray-800 group-hover:bg-gray-800">
                    {getIcon(res.result_type, res.subtype)}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center space-x-2">
                      <span className="text-sm font-medium text-gray-200 truncate">
                        {res.title}
                      </span>
                      {res.current_status && (
                        <span className="text-[9px] uppercase font-bold px-1.5 py-0.5 rounded bg-gray-900 text-gray-400 border border-gray-800">
                          {res.current_status}
                        </span>
                      )}
                      {res.confidence !== undefined &&
                        res.confidence !== null && (
                          <span className="text-[9px] font-mono font-bold text-gray-500 ml-auto">
                            {formatConfidence(res.confidence)}
                          </span>
                        )}
                    </div>

                    <div className="flex items-center space-x-3 mt-1 text-xs text-gray-500 font-mono">
                      <span className="uppercase tracking-wider text-[10px] text-gray-400">
                        {res.subtype || res.result_type}
                      </span>
                      {res.timestamp && (
                        <span>{formatDate(res.timestamp)}</span>
                      )}
                      {res.evidence_count !== undefined &&
                        res.evidence_count > 0 && (
                          <span className="flex items-center space-x-1 text-blue-500/70">
                            <FileCheck className="w-3 h-3" />
                            <span>{res.evidence_count} sources</span>
                          </span>
                        )}
                    </div>

                    {res.snippet && (
                      <p className="mt-1.5 text-xs text-gray-400 line-clamp-2 italic border-l border-gray-800 pl-2">
                        "{res.snippet}"
                      </p>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
