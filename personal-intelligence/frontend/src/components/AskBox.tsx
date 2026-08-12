import React, { useState } from "react";
import {
  AlertCircle,
  Brain,
  CheckCircle2,
  FileText,
  Send,
  Sparkles,
} from "lucide-react";
import { useAskQuestion } from "../hooks/useWorldModel";
import { formatDate } from "../utils/formatters";

export const AskBox: React.FC = () => {
  const [question, setQuestion] = useState<string>("");
  const { response, loading, error, ask, reset } = useAskQuestion();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || loading) return;
    try {
      await ask({ question: question.trim(), purpose: "user_query" });
    } catch {
      // Handled by hook state
    }
  };

  const exampleQueries = [
    "What is happening with Personal Intelligence V0?",
    "Who is responsible for Project Phoenix?",
    "What decisions were made regarding databases?",
    "What changed recently in my team?",
  ];

  return (
    <div className="w-full bg-gradient-to-b from-gray-900 to-gray-950 border border-gray-800 rounded-xl p-6 shadow-xl space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2.5">
          <div className="p-2 bg-purple-900/50 border border-purple-700/50 rounded-lg text-purple-300">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">
              Ask World Model
            </h3>
            <p className="text-xs text-gray-400">
              Query personal cognitive state via Personal Context Engine &
              optional reasoning layer
            </p>
          </div>
        </div>

        {response && (
          <button
            onClick={reset}
            className="text-xs text-gray-400 hover:text-white underline cursor-pointer"
          >
            Clear Query
          </button>
        )}
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="relative">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about your projects, relationships, commitments, or state changes..."
            rows={2}
            className="w-full bg-gray-950 border border-gray-800 focus:border-purple-500 rounded-xl p-3.5 pr-12 text-sm text-gray-100 placeholder-gray-500 focus:outline-none transition-colors resize-none"
          />
          <button
            type="submit"
            disabled={!question.trim() || loading}
            className="absolute right-3 bottom-3 p-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 disabled:opacity-50 text-white rounded-lg transition-all shadow-md cursor-pointer disabled:cursor-not-allowed"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>

        <div className="flex flex-wrap gap-2 pt-1">
          <span className="text-[11px] font-medium text-gray-500 flex items-center">
            Examples:
          </span>
          {exampleQueries.map((ex, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setQuestion(ex)}
              className="text-[11px] bg-gray-900 hover:bg-gray-800 text-gray-300 border border-gray-800 hover:border-gray-700 px-2.5 py-1 rounded-full transition-colors cursor-pointer"
            >
              {ex}
            </button>
          ))}
        </div>
      </form>

      {loading && (
        <div className="p-6 bg-gray-950/60 border border-purple-900/40 rounded-xl flex items-center space-x-3 text-purple-300 animate-pulse">
          <Brain className="w-5 h-5 animate-bounce" />
          <span className="text-sm font-medium">
            Filtering ContextPackage through Privacy Filter & Reasoning Layer...
          </span>
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-950/50 border border-red-900/60 rounded-xl text-red-300 text-sm flex items-start space-x-2.5">
          <AlertCircle className="w-5 h-5 shrink-0 text-red-400 mt-0.5" />
          <div>
            <p className="font-semibold">Reasoning Error</p>
            <p className="text-xs text-red-300/80 mt-1">{error}</p>
          </div>
        </div>
      )}

      {response && (
        <div className="space-y-4 pt-2 border-t border-gray-800">
          <div className="p-5 bg-gray-950 border border-purple-900/40 rounded-xl space-y-3">
            <div className="flex items-center space-x-2 text-xs font-semibold text-purple-400">
              <CheckCircle2 className="w-4 h-4" />
              <span>Reasoning Answer</span>
            </div>
            <p className="text-sm text-gray-100 leading-relaxed font-sans">
              {response.answer}
            </p>
          </div>

          {response.uncertainties.length > 0 && (
            <div className="p-4 bg-amber-950/30 border border-amber-900/40 rounded-xl space-y-2">
              <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
                Identified Gaps & Uncertainties
              </span>
              <ul className="list-disc list-inside text-xs text-amber-200/80 space-y-1">
                {response.uncertainties.map((u, idx) => (
                  <li key={idx}>{u}</li>
                ))}
              </ul>
            </div>
          )}

          {response.supporting_context && (
            <div className="p-4 bg-gray-900/60 border border-gray-800 rounded-xl space-y-3 text-xs">
              <div className="flex items-center justify-between text-gray-400">
                <span className="font-semibold text-gray-300 flex items-center space-x-1.5">
                  <FileText className="w-3.5 h-3.5 text-blue-400" />
                  <span>Supporting ContextPackage</span>
                </span>
                <span>
                  Assembled{" "}
                  {formatDate(response.supporting_context.assembled_at)}
                </span>
              </div>
              <p className="text-gray-400">
                {response.supporting_context.summary}
              </p>

              <div className="flex flex-wrap gap-2 pt-1 text-[11px]">
                <span className="px-2 py-0.5 bg-blue-950 text-blue-300 border border-blue-800 rounded">
                  Entities: {response.supporting_context.entities.length}
                </span>
                <span className="px-2 py-0.5 bg-purple-950 text-purple-300 border border-purple-800 rounded">
                  Relationships:{" "}
                  {response.supporting_context.relationships.length}
                </span>
                <span className="px-2 py-0.5 bg-amber-950 text-amber-300 border border-amber-800 rounded">
                  Decisions: {response.supporting_context.decisions.length}
                </span>
                <span className="px-2 py-0.5 bg-emerald-950 text-emerald-300 border border-emerald-800 rounded">
                  Evidence Records: {response.evidence.length}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
