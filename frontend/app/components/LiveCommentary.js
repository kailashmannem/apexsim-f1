"use client";

import { useRef, useEffect } from "react";

/**
 * Live commentary log with auto-scroll.
 */
export default function LiveCommentary({ entries, pendingWaypoint }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries.length]);

  return (
    <div className="commentary-section">
      <h3>AI Commentary</h3>
      {pendingWaypoint != null && (
        <div className="commentary-pending">
          <span className="spinner" /> IBM insight running for Lap{" "}
          {pendingWaypoint}…
        </div>
      )}
      <div className="commentary-log">
        {entries.length === 0 && (
          <div className="commentary-entry">
            Load a session and press Play to begin telemetry coaching.
          </div>
        )}
        {entries.map((entry, i) => (
          <div className="commentary-entry" key={i}>
            <code>{entry.timestamp}</code>
            Lap {entry.lap}: {entry.text}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
