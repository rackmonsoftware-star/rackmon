import { useState } from "react";

import { api } from "../api";
import { useAuth } from "../auth";
import { usePoll } from "../hooks";
import { usePrefs } from "../prefs";

const DISMISS_KEY = "rm_dismissed_announcement";

const LEVEL: Record<string, string> = {
  info: "#22D3EE",
  success: "#34D399",
  warning: "#FBBF24",
  critical: "#F87171",
};

/** Only allow http/https hrefs from the server-fetched update manifest (React
 * does not sanitize href, so a javascript:/data: URL would otherwise be live). */
function safeUrl(u?: string | null): string | null {
  if (!u) return null;
  try {
    const proto = new URL(u, window.location.origin).protocol;
    return proto === "http:" || proto === "https:" ? u : null;
  } catch {
    return null;
  }
}

/**
 * Opt-in update / vendor-announcement banner. Renders nothing unless the
 * update-check feature is enabled server-side AND there is something to show:
 * an available update (admins only) or a broadcast announcement (everyone,
 * dismissible). No network cost when disabled — the endpoint just echoes the
 * current version.
 */
export default function UpdateBanner() {
  const { can } = useAuth();
  const { t } = usePrefs();
  const { data } = usePoll(() => api.updateStatus(), 0); // once per mount; server caches 6h
  const [dismissed, setDismissed] = useState<string>(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) || "";
    } catch {
      return "";
    }
  });

  if (!data) return null;
  const ann = data.announcement;
  const showAnn = !!ann && ann.id !== dismissed;
  const showUpdate = data.update_available && can("admin");
  if (!showAnn && !showUpdate) return null;

  return (
    <div className="mx-auto max-w-7xl space-y-2 px-4 pt-3">
      {showUpdate && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-accent/40 bg-accent/10 px-4 py-2 text-sm">
          <span className="rounded bg-accent px-1.5 py-0.5 text-[10px] font-bold uppercase text-[color:var(--accent-ink)]">
            {t("update")}
          </span>
          <span className="text-ink">
            {t("updateAvailable")} <span className="mono">{data.current}</span>
            {" → "}
            <span className="mono font-semibold">{data.latest}</span>
          </span>
          {data.notes && <span className="text-muted">· {data.notes}</span>}
          {safeUrl(data.download_url) && (
            <a
              href={safeUrl(data.download_url)!}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-auto shrink-0 font-medium text-accent hover:underline"
            >
              {t("viewUpdate")} →
            </a>
          )}
        </div>
      )}
      {showAnn && ann && (
        <div
          className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-4 py-2 text-sm"
          style={{
            borderColor: `${LEVEL[ann.level] || "#334155"}66`,
            background: `${LEVEL[ann.level] || "#22D3EE"}14`,
          }}
        >
          <span
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: LEVEL[ann.level] || "#22D3EE" }}
          />
          {ann.title && <span className="font-semibold text-ink">{ann.title}</span>}
          {ann.body && <span className="text-muted">{ann.body}</span>}
          {safeUrl(ann.link) && (
            <a
              href={safeUrl(ann.link)!}
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 font-medium text-accent hover:underline"
            >
              {t("viewUpdate")} →
            </a>
          )}
          <button
            className="ml-auto shrink-0 text-muted hover:text-ink"
            aria-label={t("dismiss")}
            onClick={() => {
              try {
                localStorage.setItem(DISMISS_KEY, ann.id);
              } catch {
                /* ignore */
              }
              setDismissed(ann.id);
            }}
          >
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
