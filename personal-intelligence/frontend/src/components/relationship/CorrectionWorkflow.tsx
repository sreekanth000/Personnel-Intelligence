import React, { useState } from "react";
import { worldApi } from "../../api";
import { CheckCircle2, Edit2, XCircle, Clock } from "lucide-react";

interface CorrectionWorkflowProps {
  relationshipId: string;
  currentSubject: string;
  currentPredicate: string;
  currentObject: string;
  onCorrected: () => void;
}

export const CorrectionWorkflow: React.FC<CorrectionWorkflowProps> = ({
  relationshipId,
  currentSubject,
  currentPredicate,
  currentObject,
  onCorrected,
}) => {
  const [mode, setMode] = useState<
    "idle" | "confirm" | "reject" | "outdate" | "correct"
  >("idle");
  const [reason, setReason] = useState("");

  const [editSubject, setEditSubject] = useState(currentSubject);
  const [editPredicate, setEditPredicate] = useState(currentPredicate);
  const [editObject, setEditObject] = useState(currentObject);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (
    action: "confirm" | "reject" | "correct" | "outdate",
  ) => {
    if (action === "correct" && !reason.trim()) {
      setError("A reason is required for correction.");
      return;
    }

    if (!reason.trim() && action !== "confirm") {
      setError("Please provide a reason for this action.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await worldApi.submitCorrection(
        relationshipId,
        action,
        reason || "User confirmed",
        action === "correct"
          ? {
              new_subject: editSubject,
              new_predicate: editPredicate,
              new_object: editObject,
            }
          : undefined,
      );
      setMode("idle");
      setReason("");
      onCorrected();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to submit correction.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = () => {
    setMode("idle");
    setError(null);
    setReason("");
    setEditSubject(currentSubject);
    setEditPredicate(currentPredicate);
    setEditObject(currentObject);
  };

  return (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700 shadow-md">
      <h3 className="text-sm font-semibold text-slate-200 mb-3 uppercase tracking-wider">
        Correct Intelligence
      </h3>

      {mode === "idle" ? (
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => setMode("confirm")}
            className="flex items-center justify-center gap-2 px-3 py-2 bg-emerald-900/30 text-emerald-400 border border-emerald-900/50 hover:bg-emerald-900/50 hover:border-emerald-700 rounded transition-colors text-sm"
          >
            <CheckCircle2 size={16} />
            Confirm
          </button>
          <button
            onClick={() => setMode("correct")}
            className="flex items-center justify-center gap-2 px-3 py-2 bg-blue-900/30 text-blue-400 border border-blue-900/50 hover:bg-blue-900/50 hover:border-blue-700 rounded transition-colors text-sm"
          >
            <Edit2 size={16} />
            Correct
          </button>
          <button
            onClick={() => setMode("reject")}
            className="flex items-center justify-center gap-2 px-3 py-2 bg-red-900/30 text-red-400 border border-red-900/50 hover:bg-red-900/50 hover:border-red-700 rounded transition-colors text-sm"
          >
            <XCircle size={16} />
            Reject
          </button>
          <button
            onClick={() => setMode("outdate")}
            className="flex items-center justify-center gap-2 px-3 py-2 bg-slate-700/50 text-slate-300 border border-slate-600 hover:bg-slate-600 hover:border-slate-500 rounded transition-colors text-sm"
          >
            <Clock size={16} />
            Outdated
          </button>
        </div>
      ) : (
        <div className="space-y-4 animate-in fade-in zoom-in-95 duration-200">
          {mode === "correct" && (
            <div className="space-y-3 bg-slate-900/50 p-3 rounded-md border border-slate-700/50">
              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Subject
                </label>
                <input
                  type="text"
                  value={editSubject}
                  onChange={(e) => setEditSubject(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Predicate
                </label>
                <input
                  type="text"
                  value={editPredicate}
                  onChange={(e) => setEditPredicate(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Object
                </label>
                <input
                  type="text"
                  value={editObject}
                  onChange={(e) => setEditObject(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs text-slate-400 mb-1">
              Reason for action{" "}
              {mode !== "confirm" && <span className="text-red-400">*</span>}
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={
                mode === "confirm"
                  ? "Optional reason..."
                  : "Why is this being changed?"
              }
              className="w-full bg-slate-900/80 border border-slate-600 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500 min-h-[80px]"
            />
          </div>

          {error && (
            <div className="text-xs text-red-400 bg-red-900/20 px-3 py-2 rounded">
              {error}
            </div>
          )}

          <div className="flex gap-2 justify-end">
            <button
              onClick={cancel}
              disabled={submitting}
              className="px-3 py-1.5 text-sm text-slate-300 hover:text-white disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={() => handleSubmit(mode)}
              disabled={submitting}
              className={`px-4 py-1.5 text-sm font-medium rounded text-white shadow disabled:opacity-50
                ${mode === "confirm" ? "bg-emerald-600 hover:bg-emerald-500" : ""}
                ${mode === "correct" ? "bg-blue-600 hover:bg-blue-500" : ""}
                ${mode === "reject" ? "bg-red-600 hover:bg-red-500" : ""}
                ${mode === "outdate" ? "bg-slate-600 hover:bg-slate-500" : ""}
              `}
            >
              {submitting ? "Saving..." : "Submit"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
