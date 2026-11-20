import type { CSSProperties } from "react";

/**
 * Placeholder blocks shown while data loads, in the shape of what is coming (forensics Q2: a
 * skeleton tells the reader where things will appear; a spinner only says "wait"). Styled in
 * shell/shell.css; outside the new shell they fall back to a neutral grey.
 */
export function Skeleton({ width = "100%", height = 14, radius = 6, style }: {
  width?: number | string;
  height?: number | string;
  radius?: number;
  style?: CSSProperties;
}) {
  return <span className="skeleton" aria-hidden="true" style={{ width, height, borderRadius: radius, ...style }} />;
}

/** A few text lines, the last one shorter, like a paragraph. */
export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton-text" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 && lines > 1 ? "60%" : "100%"} />
      ))}
    </div>
  );
}

/** Generic page placeholder: a summary line and a list. Pages get their own shapes in later PRs. */
export function PageSkeleton() {
  return (
    <div className="page-skeleton" role="status" aria-live="polite">
      <span className="visually-hidden">Wird geladen …</span>
      <Skeleton width="45%" height={20} />
      <Skeleton width="70%" />
      <div className="page-skeleton-list">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="page-skeleton-row">
            <div style={{ flex: 1, display: "grid", gap: 6 }}>
              <Skeleton width={`${55 + ((i * 17) % 35)}%`} />
              <Skeleton width="35%" height={10} />
            </div>
            <Skeleton width={64} height={12} />
          </div>
        ))}
      </div>
    </div>
  );
}
