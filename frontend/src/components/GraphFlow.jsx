import { AWAITING_APPROVAL } from "../lib/status.js";

const STEPS = [
  { key: "researching", label: "Research Agent", sub: "fetch_trending_headlines()" },
  { key: "writing", label: "Scriptwriter", sub: "PAX / Caveman JSON" },
  { key: "reviewing", label: "Duration Check", sub: "word_count / 2.4" },
  { key: "rendering", label: "Render", sub: "Pexels + FFmpeg" },
  { key: "recovering", label: "Recovery Agent", sub: "on render failure" },
  {
    key: AWAITING_APPROVAL,
    label: "Admin Approval",
    sub: "preview the reel · human gate",
  },
  { key: "posting", label: "Publish", sub: "Facebook + LinkedIn" },
  { key: "done", label: "Done", sub: "reel is live" },
];

function stepState(step, status) {
  const order = STEPS.map((s) => s.key);

  // A rejection stops the run at the same step it approved from.
  const currentIdx = order.indexOf(
    status === "rejected" ? AWAITING_APPROVAL : status
  );
  const stepIdx = order.indexOf(step.key);

  if (status === "rejected") {
    if (stepIdx < currentIdx) return "done";
    if (stepIdx === currentIdx) return "error";
    return "";
  }
  if (status === "failed") return stepIdx <= currentIdx ? "error" : "";
  if (stepIdx < currentIdx) return "done";
  if (stepIdx === currentIdx) return "active";
  return "";
}

export default function GraphFlow({ status }) {
  return (
    <div>
      <p className="panel-title">Pipeline</p>
      {STEPS.map((step, i) => {
        const cls = status ? stepState(step, status) : "";
        return (
          <div key={step.key} className={`flow-step ${cls}`}>
            <div className="flow-index">{i + 1}</div>
            <div>
              <div className="flow-label">{step.label}</div>
              <div className="flow-sub">{step.sub}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
