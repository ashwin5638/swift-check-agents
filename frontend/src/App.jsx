import { useCallback, useEffect, useRef, useState } from "react";
import GraphFlow from "./components/GraphFlow.jsx";
import RunList from "./components/RunList.jsx";
import StateViewer from "./components/StateViewer.jsx";
import LogPanel from "./components/LogPanel.jsx";
import {
  startRun,
  listRuns,
  getRun,
  getSchedule,
  approveRun,
  rejectRun,
  connectRunSocket,
} from "./api.js";
import { isSettled, prettyStatus, statusDotClass } from "./lib/status.js";

const STORAGE_KEY = "wire-room:run-id";
const RECONNECT_LIMIT = 6;
const RECONNECT_BASE_MS = 1000;

function readStoredRunId() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredRunId(runId) {
  try {
    if (runId) window.localStorage.setItem(STORAGE_KEY, runId);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* private mode / storage disabled — resume is a nicety, not a requirement */
  }
}

export default function App() {
  const [state, setState] = useState({});
  const [logs, setLogs] = useState([]);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState(readStoredRunId);
  const [runsLoading, setRunsLoading] = useState(true);
  const [live, setLive] = useState(false);
  const [schedule, setSchedule] = useState(null);
  const [deciding, setDeciding] = useState(false);

  const wsRef = useRef(null);
  const retryRef = useRef(0);
  const reconnectTimerRef = useRef(null);
  const watchedRunRef = useRef(null);

  // A run parked at the approval gate is not computing anything, so it must
  // not hold the pipeline hostage — only an in-flight node does that.
  const running = Boolean(state.status) && !isSettled(state.status);
  const watchingLiveRun = live && running;

  const appendLocalLog = useCallback((message) => {
    setLogs((prev) => [
      ...prev,
      { ts: Date.now() / 1000, node: "dashboard", message },
    ]);
  }, []);

  const refreshRuns = useCallback(async () => {
    try {
      setRuns(await listRuns());
    } catch (err) {
      appendLocalLog(`Could not load run history: ${err.message}`);
    } finally {
      setRunsLoading(false);
    }
  }, [appendLocalLog]);

  const teardownSocket = useCallback(() => {
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    setLive(false);
  }, []);

  const handleMessage = useCallback((msg) => {
    if (msg.type === "snapshot") {
      setState(msg.state || {});
      setLogs(msg.logs || []);
      return;
    }
    if (msg.type === "state") {
      setState(msg.state || {});
      return;
    }
    if (msg.type === "log") {
      setLogs((prev) => [...prev, msg.entry]);
    }
  }, []);

  const connect = useCallback(
    (id) => {
      const ws = connectRunSocket(id, handleMessage);
      wsRef.current = ws;

      ws.onopen = () => {
        retryRef.current = 0;
        setLive(true);
      };

      ws.onclose = () => {
        if (wsRef.current !== ws) return;
        setLive(false);
        if (watchedRunRef.current !== id) return;
        if (retryRef.current >= RECONNECT_LIMIT) {
          appendLocalLog(`Lost live connection to run ${id.slice(0, 8)} — giving up.`);
          return;
        }
        const delay = RECONNECT_BASE_MS * 2 ** retryRef.current;
        retryRef.current += 1;
        reconnectTimerRef.current = window.setTimeout(() => connect(id), delay);
      };

      ws.onerror = () => ws.close();
    },
    [appendLocalLog, handleMessage]
  );

  // Snapshot first, then stream: a dropped socket can never leave us blank.
  const watch = useCallback(
    async (id) => {
      watchedRunRef.current = id;
      retryRef.current = 0;
      teardownSocket();
      setRunId(id);
      writeStoredRunId(id);

      try {
        const snapshot = await getRun(id);
        if (watchedRunRef.current !== id) return;
        handleMessage(snapshot);
      } catch (err) {
        if (watchedRunRef.current !== id) return;
        watchedRunRef.current = null;
        setRunId(null);
        writeStoredRunId(null);
        setState({});
        setLogs([]);
        appendLocalLog(`Run ${id.slice(0, 8)} is no longer on the server.`);
        refreshRuns();
        return;
      }

      if (watchedRunRef.current === id) connect(id);
    },
    [appendLocalLog, connect, handleMessage, refreshRuns, teardownSocket]
  );

  const handleRun = useCallback(async () => {
    setState({ status: "queued" });
    setLogs([]);
    setRunId(null);
    writeStoredRunId(null);

    try {
      const { run_id } = await startRun();
      await watch(run_id);
      await refreshRuns();
    } catch (err) {
      appendLocalLog(`Failed to start run: ${err.message}`);
      refreshRuns();
    }
  }, [appendLocalLog, refreshRuns, watch]);

  // A run id is the unit of authority for both decisions, so they are only
  // offered against the run currently on the gate.
  const handleApprove = useCallback(
    async (caption) => {
      if (!runId) return;
      setDeciding(true);
      try {
        await approveRun(runId, caption);
        appendLocalLog("Approved — uploading to social platforms.");
      } catch (err) {
        appendLocalLog(`Approval failed: ${err.message}`);
      } finally {
        setDeciding(false);
      }
    },
    [appendLocalLog, runId]
  );

  const handleReject = useCallback(
    async (note) => {
      if (!runId) return;
      setDeciding(true);
      try {
        await rejectRun(runId, note);
        appendLocalLog("Rejected — nothing will be published.");
        refreshRuns();
      } catch (err) {
        appendLocalLog(`Rejection failed: ${err.message}`);
      } finally {
        setDeciding(false);
      }
    },
    [appendLocalLog, refreshRuns, runId]
  );

  useEffect(() => {
    refreshRuns();
    getSchedule()
      .then(setSchedule)
      .catch(() => setSchedule(null));
  }, [refreshRuns]);

  // Resume the run that was live when the page was last closed.
  useEffect(() => {
    const stored = readStoredRunId();
    if (stored) watch(stored);
  }, [watch]);

  useEffect(() => teardownSocket, [teardownSocket]);

  // Keep the history list honest without polling the endpoint forever.
  useEffect(() => {
    if (!watchingLiveRun) return undefined;
    const id = setInterval(refreshRuns, 5000);
    return () => clearInterval(id);
  }, [watchingLiveRun, refreshRuns]);

  // A settled run is final — the interval would otherwise keep polling.
  // "Awaiting approval" counts: the run has stopped, only a human moves it.
  useEffect(() => {
    if (isSettled(state.status)) refreshRuns();
  }, [state.status, refreshRuns]);

  return (
    <>
      <header className="topbar">
        <div className="masthead">
          <h1>Swift-Check</h1>
          <span className="tagline">Daily maritime news-reel pipeline · LangGraph control room</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {schedule && (
            <span className="status-pill" title="Length window and daily schedule">
              {schedule.length_window[0]}–{schedule.length_window[1]}s
              {schedule.enabled ? ` · daily ${schedule.at}` : ""}
            </span>
          )}
          <span className="status-pill">
            <span className={`status-dot ${statusDotClass(state.status)}`} />
            {prettyStatus(state.status)}
            {state.trigger === "scheduled" ? " · auto" : ""}
            {runId && running && !live ? " · reconnecting" : ""}
          </span>
          <button className="run-button" onClick={handleRun} disabled={watchingLiveRun}>
            {watchingLiveRun ? "Running…" : "Run Pipeline"}
          </button>
        </div>
      </header>

      <main className="control-room">
        <section className="panel">
          <RunList
            runs={runs}
            activeRunId={runId}
            loading={runsLoading}
            onSelect={watch}
          />
        </section>
        <section className="panel">
          <GraphFlow status={state.status} />
        </section>
        <section className="panel">
          <StateViewer
            state={state}
            runId={runId}
            platforms={schedule?.platforms || []}
            busy={deciding}
            onApprove={handleApprove}
            onReject={handleReject}
          />
        </section>
        <section className="panel">
          <LogPanel logs={logs} />
        </section>
      </main>
    </>
  );
}
