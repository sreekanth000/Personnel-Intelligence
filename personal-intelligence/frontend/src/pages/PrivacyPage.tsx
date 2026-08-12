import React from "react";
import {
  ShieldAlert,
  Database,
  HardDrive,
  Cloud,
  Lock,
  ArrowDown,
  Server,
  BrainCircuit,
  Mail,
  Zap,
  Globe,
} from "lucide-react";

interface FlowStageProps {
  id: string;
  title: string;
  icon: React.ReactNode;
  location: "LOCAL" | "EXTERNAL";
  control: "USER CONTROLLED" | "PROVIDER CONTROLLED";
  stored: string;
  leavesMachine: string | null;
  encrypted: string;
  retained: string;
  description: string;
  isLast?: boolean;
}

const FlowStage: React.FC<FlowStageProps> = ({
  title,
  icon,
  location,
  control,
  stored,
  leavesMachine,
  encrypted,
  retained,
  description,
  isLast,
}) => {
  const isLocal = location === "LOCAL";
  const isUserControl = control === "USER CONTROLLED";

  return (
    <div className="flex flex-col items-center">
      <div
        className={`w-full max-w-3xl rounded-xl border-2 p-5 ${
          isLocal
            ? "bg-slate-900 border-slate-700 shadow-[0_0_15px_rgba(30,41,59,0.5)]"
            : "bg-indigo-950/40 border-indigo-900/60 shadow-[0_0_15px_rgba(49,46,129,0.3)]"
        }`}
      >
        <div className="flex items-start gap-4">
          <div
            className={`p-3 rounded-lg flex-shrink-0 ${
              isLocal
                ? "bg-slate-800 text-slate-300"
                : "bg-indigo-900/50 text-indigo-300"
            }`}
          >
            {icon}
          </div>

          <div className="flex-1">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-xl font-bold text-slate-100">{title}</h3>
              <div className="flex gap-2">
                <span
                  className={`text-[10px] font-bold px-2 py-1 rounded tracking-wider ${
                    isLocal
                      ? "bg-emerald-900/40 text-emerald-400 border border-emerald-900"
                      : "bg-amber-900/40 text-amber-400 border border-amber-900"
                  }`}
                >
                  {location}
                </span>
                <span
                  className={`text-[10px] font-bold px-2 py-1 rounded tracking-wider ${
                    isUserControl
                      ? "bg-blue-900/40 text-blue-400 border border-blue-900"
                      : "bg-purple-900/40 text-purple-400 border border-purple-900"
                  }`}
                >
                  {control}
                </span>
              </div>
            </div>

            <p className="text-sm text-slate-400 mb-4">{description}</p>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="bg-black/20 p-2 rounded border border-white/5 flex gap-2">
                <Database className="w-4 h-4 text-slate-500 shrink-0" />
                <div>
                  <span className="block text-slate-500 mb-0.5">Stored</span>
                  <span className="text-slate-300 font-medium">{stored}</span>
                </div>
              </div>

              <div
                className={`bg-black/20 p-2 rounded border border-white/5 flex gap-2 ${leavesMachine ? "bg-red-950/10 border-red-900/20" : ""}`}
              >
                <Globe
                  className={`w-4 h-4 shrink-0 ${leavesMachine ? "text-red-400" : "text-slate-500"}`}
                />
                <div>
                  <span className="block text-slate-500 mb-0.5">
                    Leaves Machine
                  </span>
                  <span
                    className={`font-medium ${leavesMachine ? "text-red-300" : "text-slate-300"}`}
                  >
                    {leavesMachine || "None"}
                  </span>
                </div>
              </div>

              <div className="bg-black/20 p-2 rounded border border-white/5 flex gap-2">
                <Lock className="w-4 h-4 text-emerald-500 shrink-0" />
                <div>
                  <span className="block text-slate-500 mb-0.5">Encrypted</span>
                  <span className="text-slate-300 font-medium">
                    {encrypted}
                  </span>
                </div>
              </div>

              <div className="bg-black/20 p-2 rounded border border-white/5 flex gap-2">
                <HardDrive className="w-4 h-4 text-slate-500 shrink-0" />
                <div>
                  <span className="block text-slate-500 mb-0.5">Retained</span>
                  <span className="text-slate-300 font-medium">{retained}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {!isLast && (
        <div className="my-2 h-8 flex items-center justify-center">
          <div className="h-full w-0.5 bg-slate-700"></div>
          <ArrowDown className="absolute text-slate-500 w-5 h-5 bg-slate-950 rounded-full" />
        </div>
      )}
    </div>
  );
};

export const PrivacyPage: React.FC = () => {
  const stages: FlowStageProps[] = [
    {
      id: "gmail",
      title: "Gmail API",
      icon: <Mail className="w-6 h-6" />,
      location: "EXTERNAL",
      control: "PROVIDER CONTROLLED",
      stored: "Original Emails",
      leavesMachine: null,
      encrypted: "In transit (TLS)",
      retained: "Indefinitely by Google",
      description:
        "Source of your personal data. We pull messages using the official Gmail API via OAuth2.",
    },
    {
      id: "local_store",
      title: "Local Observation Store",
      icon: <Database className="w-6 h-6" />,
      location: "LOCAL",
      control: "USER CONTROLLED",
      stored: "Raw Email Content (SQLite)",
      leavesMachine: null,
      encrypted: "At rest (Optional OS level)",
      retained: "Until explicitly deleted",
      description:
        "Emails are downloaded and stored locally on your device to create a fast, offline archive.",
    },
    {
      id: "gpt4",
      title: "GPT-4.1 LLM",
      icon: <Cloud className="w-6 h-6" />,
      location: "EXTERNAL",
      control: "PROVIDER CONTROLLED",
      stored: "Ephemerally during processing",
      leavesMachine: "Full Email Content",
      encrypted: "In transit (TLS)",
      retained: "Zero Data Retention (API policy)",
      description:
        "Used to extract structured entities and relationships from unstructured text.",
    },
    {
      id: "extraction",
      title: "Extraction Pipeline",
      icon: <Zap className="w-6 h-6" />,
      location: "LOCAL",
      control: "USER CONTROLLED",
      stored: "Structured JSON",
      leavesMachine: null,
      encrypted: "At rest (Optional OS level)",
      retained: "Temporary during processing",
      description:
        "Validates and cleans the intelligence extracted by the external LLM before saving.",
    },
    {
      id: "world_model",
      title: "Personal World Model",
      icon: <Server className="w-6 h-6" />,
      location: "LOCAL",
      control: "USER CONTROLLED",
      stored: "Knowledge Graph (DuckDB & Kuzu)",
      leavesMachine: null,
      encrypted: "At rest (Optional OS level)",
      retained: "Indefinitely (Your Archive)",
      description:
        "The core intelligence database. It stores the synthesized graph of your life and relationships.",
    },
    {
      id: "context_engine",
      title: "Context Engine",
      icon: <BrainCircuit className="w-6 h-6" />,
      location: "LOCAL",
      control: "USER CONTROLLED",
      stored: "Contextual Prompts",
      leavesMachine: null,
      encrypted: "In memory",
      retained: "Ephemeral",
      description:
        "Synthesizes context from your World Model to answer questions or assist with tasks.",
    },
    {
      id: "external_ai",
      title: "External AI Assistant",
      icon: <Cloud className="w-6 h-6" />,
      location: "EXTERNAL",
      control: "PROVIDER CONTROLLED",
      stored: "Ephemerally during chat",
      leavesMachine: "Synthesized Context & User Query",
      encrypted: "In transit (TLS)",
      retained: "Based on provider policy",
      description:
        "The final LLM that answers your questions using the context provided by the Context Engine.",
    },
  ];

  return (
    <div className="flex h-screen bg-slate-950 overflow-hidden">
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-5xl mx-auto px-8 py-12">
          <div className="mb-10 text-center">
            <h1 className="text-4xl font-bold text-slate-100 mb-4 tracking-tight">
              Privacy & Data Flow
            </h1>
            <p className="text-lg text-slate-400 max-w-2xl mx-auto">
              Transparency is our core principle. Understand exactly where your
              data lives, when it leaves your machine, and who controls it.
            </p>
          </div>

          <div className="bg-red-950/40 border-2 border-red-900/50 rounded-xl p-6 mb-12 flex items-start gap-4 shadow-[0_0_30px_rgba(153,27,27,0.15)] animate-in fade-in slide-in-from-bottom-4">
            <div className="bg-red-900/50 p-3 rounded-full shrink-0">
              <ShieldAlert className="w-8 h-8 text-red-400" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-red-300 mb-2">
                CRITICAL PRIVACY WARNING
              </h2>
              <p className="text-red-200/80 leading-relaxed">
                <strong className="text-red-200">
                  Gmail content is sent to GPT-4.1 for extraction.
                </strong>
                <br className="mb-2" />
                Do not assume that your data is entirely private merely because
                this application runs locally. While your permanent database is
                local, the raw text of your emails is transmitted over the
                internet to OpenAI (or your configured LLM provider) to extract
                relationships and intelligence.
              </p>
            </div>
          </div>

          <div className="py-8 animate-in fade-in slide-in-from-bottom-8 duration-500">
            {stages.map((stage, index) => (
              <FlowStage
                key={stage.id}
                {...stage}
                isLast={index === stages.length - 1}
              />
            ))}
          </div>
        </div>
      </main>
    </div>
  );
};
