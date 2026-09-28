export default function LogPanel({ logs }) {
  return (
    <div>
      <p className="panel-title">Live Log</p>
      {logs.length === 0 && (
        <div className="empty-state">Logs will stream here once a run starts.</div>
      )}
      {logs
        .slice()
        .reverse()
        .map((entry, i) => (
          <div className="log-line" key={i}>
            <span className="log-time">
              {new Date(entry.ts * 1000).toLocaleTimeString()}
            </span>
            <span className="log-node">{entry.node}</span>
            <span className="log-msg">{entry.message}</span>
          </div>
        ))}
    </div>
  );
}
