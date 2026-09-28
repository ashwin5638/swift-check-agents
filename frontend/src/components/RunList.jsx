import {
  AWAITING_APPROVAL,
  shortId,
  statusDotClass,
  prettyStatus,
  formatClock,
} from "../lib/status.js";

export default function RunList({ runs, activeRunId, loading, onSelect }) {
  return (
    <div>
      <p className="panel-title">Runs</p>

      {loading && runs.length === 0 && (
        <div className="empty-state">Loading run history…</div>
      )}

      {!loading && runs.length === 0 && (
        <div className="empty-state">No runs yet.</div>
      )}

      {runs.map((run) => {
        const held = run.status === AWAITING_APPROVAL;
        return (
          <button
            type="button"
            key={run.run_id}
            className={`run-item ${run.run_id === activeRunId ? "selected" : ""} ${
              held ? "held" : ""
            }`}
            onClick={() => onSelect(run.run_id)}
          >
            <span className="run-item-top">
              <span className={`status-dot ${statusDotClass(run.status)}`} />
              <span className="run-item-status">{prettyStatus(run.status) || "unknown"}</span>
              {held && <span className="run-item-flag">needs you</span>}
              <span className="run-item-id">{shortId(run.run_id)}</span>
            </span>
            <span className="run-item-title">{run.title || "no story selected yet"}</span>
            <span className="run-item-foot">
              <span className="run-item-time">
                {formatClock(run.created_at)}
                {run.trigger === "scheduled" ? " · auto" : ""}
              </span>
              {run.duration_sec != null && (
                <span className="run-item-time">{run.duration_sec}s</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
