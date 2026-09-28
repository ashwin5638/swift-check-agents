import { formatClock, shortId } from "../lib/status.js";
import ApprovalCard from "./ApprovalCard.jsx";
import ReelPlayer from "./ReelPlayer.jsx";

export default function StateViewer({
  state,
  runId,
  platforms,
  busy,
  onApprove,
  onReject,
}) {
  return (
    <div>
      <p className="panel-title">
        State{runId ? ` · ${shortId(runId)}` : ""}
      </p>
      {!state?.status ? (
        <div className="empty-state">
          No run selected. Press "Run Pipeline" to fetch trending headlines
          and start the graph, or pick a past run from the list.
        </div>
      ) : (
        <RunState
          state={state}
          platforms={platforms}
          busy={busy}
          onApprove={onApprove}
          onReject={onReject}
        />
      )}
    </div>
  );
}

function RunState({ state, platforms, busy, onApprove, onReject }) {
  const story = state.selected_story;
  const script = state.script;
  const render = state.render_result;
  const urls = state.social_post_urls;
  const errors = state.error_log || [];

  return (
    <div>
      {story && (
        <div className="state-card">
          <h3>Selected Story</h3>
          <div className="field">
            <span className="k">headline</span>
            <span className="v">{story.title}</span>
          </div>
          <div className="field">
            <span className="k">source</span>
            <span className="v">{story.source}</span>
          </div>
          {state.selection_reason && (
            <div className="field">
              <span className="k">why</span>
              <span className="v">{state.selection_reason}</span>
            </div>
          )}
        </div>
      )}

      {script && (
        <div className="state-card">
          <h3>{script.title}</h3>
          <div className="field">
            <span className="k">duration</span>
            <span className="v">
              {script.est_duration_sec}s{" "}
              {state.duration_check_passed ? "— within limit" : "— over limit, revising"}
              {state.critic_revision_count ? ` (rev ${state.critic_revision_count})` : ""}
            </span>
          </div>
          {script.beats?.map((b) => (
            <div className="beat-row" key={b.beat}>
              <div className="beat-tag">{b.beat}</div>
              <div>{b.voiceover}</div>
              <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 2 }}>
                clip: {b.image_query}
              </div>
            </div>
          ))}
        </div>
      )}

      {render && (
        <div className="state-card">
          <h3>Render</h3>
          {render.video_url && <ReelPlayer videoUrl={render.video_url} />}
          <div className="field">
            <span className="k">status</span>
            <span className="v">{render.status}</span>
          </div>
          {render.duration_sec != null && (
            <div className="field">
              <span className="k">length</span>
              <span className="v">
                {render.duration_sec}s
                {render.narration_sec != null &&
                  render.narration_sec !== render.duration_sec && (
                    <span style={{ color: "var(--muted)" }}>
                      {" "}
                      (narration {render.narration_sec}s
                      {render.tempo && render.tempo !== 1
                        ? `, paced ×${render.tempo}`
                        : ""}
                      )
                    </span>
                  )}
              </span>
            </div>
          )}
          {render.voice && (
            <div className="field">
              <span className="k">voice</span>
              <span className="v">
                {render.voice}
                {render.caption_cues ? ` · ${render.caption_cues} caption cues` : ""}
              </span>
            </div>
          )}
          {render.tail_hold_sec > 0 && (
            <div className="field">
              <span className="k">tail</span>
              <span className="v">
                +{render.tail_hold_sec}s held to reach minimum length
              </span>
            </div>
          )}
          {render.trimmed && (
            <div className="field">
              <span className="k">trimmed</span>
              <span className="v" style={{ color: "var(--amber)" }}>
                narration exceeded the window and was cut to fit
              </span>
            </div>
          )}
          {render.output_path && (
            <div className="field">
              <span className="k">output</span>
              <span className="v">{render.output_path}</span>
            </div>
          )}
        </div>
      )}

      {onApprove && (
        <ApprovalCard
          state={state}
          platforms={platforms}
          busy={busy}
          onApprove={onApprove}
          onReject={onReject}
        />
      )}

      {urls && Object.keys(urls).length > 0 && (
        <div className="state-card">
          <h3>Published</h3>
          <div className="field">
            <span className="k">at</span>
            <span className="v">{formatClock(state.published_at)}</span>
          </div>
          {Object.entries(urls).map(([platform, url]) => (
            <div className="field" key={platform}>
              <span className="k">{platform}</span>
              <span className="v">
                <a href={url} target="_blank" rel="noreferrer" style={{ color: "var(--amber)" }}>
                  {url}
                </a>
              </span>
            </div>
          ))}
        </div>
      )}

      {errors.length > 0 && (
        <div className="state-card" style={{ borderColor: "var(--on-air-dim)" }}>
          <h3 style={{ color: "var(--on-air)" }}>Error Log</h3>
          {errors.map((e, i) => (
            <div className="field" key={i}>
              <span className="k">{e.node}</span>
              <span className="v">
                {e.message} {e.resolved ? "(recovered)" : ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
