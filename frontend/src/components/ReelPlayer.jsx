import { mediaUrl } from "../api.js";

/**
 * The rendered reel itself, inline. This is the thing the admin is being
 * asked to approve, so it has to be the real file — not a path, not a
 * thumbnail. Renders are 1080x1920, hence the vertical frame.
 */
export default function ReelPlayer({ videoUrl }) {
  const src = mediaUrl(videoUrl);

  if (!src) {
    return (
      <div className="reel-player reel-player-missing">
        Preview unavailable — this run&apos;s render was not stored.
      </div>
    );
  }

  return (
    <div className="reel-stage">
      <video className="reel-player" src={src} controls preload="metadata" playsInline>
        Your browser cannot play this reel.{" "}
        <a href={src} target="_blank" rel="noreferrer">
          Open it directly
        </a>
        .
      </video>
    </div>
  );
}
