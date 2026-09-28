import { useEffect, useState } from "react";
import { AWAITING_APPROVAL, formatClock } from "../lib/status.js";

function suggestedCaption(title) {
  return title ? `${title} #news #shorts` : "";
}

const DECISION_COPY = {
  approved: "Approved — publishing to social media.",
  rejected: "Rejected — this reel was never published.",
};

/**
 * The gate between a finished render and the public internet. Approve and
 * Reject are only enabled while the run is parked at awaiting_approval, so
 * a second click (or a stale tab) can't re-post a reel that is already live.
 */
export default function ApprovalCard({ state, platforms = [], onApprove, onReject, busy }) {
  const approval = state.approval || {};
  const decision = approval.decision || "pending";
  const pending = state.status === AWAITING_APPROVAL;

  const title = state.script?.title;
  const suggestion = suggestedCaption(title);
  const [caption, setCaption] = useState(suggestion);
  const [note, setNote] = useState("");

  useEffect(() => {
    setCaption(suggestion);
  }, [suggestion]);

  useEffect(() => {
    if (pending) setNote("");
  }, [pending]);

  if (state.status === "researching" || !state.script) return null;

  return (
    <div className={`state-card approval-card approval-${decision}`}>
      <h3>Approval</h3>

      <div className="field">
        <span className="k">status</span>
        <span className="v">
          {decision}
          {approval.decided_at ? ` · ${formatClock(approval.decided_at)}` : ""}
        </span>
      </div>

      {approval.note && (
        <div className="field">
          <span className="k">note</span>
          <span className="v">{approval.note}</span>
        </div>
      )}

      {pending && (
        <>
          <p className="approval-hint">
            Watch the reel above. Nothing reaches a platform until you approve it.
          </p>

          <div className="field">
            <span className="k">targets</span>
            <span className="v">
              {platforms.length > 0 ? platforms.join(", ") : "no platform configured"}
            </span>
          </div>

          <label className="approval-label" htmlFor="approval-caption">
            caption
          </label>
          <textarea
            id="approval-caption"
            className="approval-input"
            rows={3}
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder="What will be published alongside the reel"
          />

          <label className="approval-label" htmlFor="approval-note">
            rejection reason (optional)
          </label>
          <input
            id="approval-note"
            className="approval-input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Only used if you reject"
          />

          <div className="approval-actions">
            <button
              type="button"
              className="approve-button"
              disabled={busy}
              onClick={() => onApprove(caption)}
            >
              {busy ? "Publishing…" : "Approve & publish"}
            </button>
            <button
              type="button"
              className="reject-button"
              disabled={busy}
              onClick={() => onReject(note)}
            >
              Reject
            </button>
          </div>
        </>
      )}

      {!pending && decision !== "pending" && (
        <p className="approval-verdict">{DECISION_COPY[decision]}</p>
      )}
    </div>
  );
}
