import { useEffect, useRef, useState } from "react";

import { ApiError, api, type SupportKind } from "../api";
import { useAuth } from "../auth";
import { usePrefs } from "../prefs";

const KINDS: SupportKind[] = ["bug", "idea", "question"];

/**
 * Floating "Feedback" button + panel, shown on every authenticated page. Lets a
 * user send a bug report, an idea or a question to the vendor (forwarded
 * server-side by the instance, so no vendor URL is ever exposed to the browser).
 */
export default function SupportWidget() {
  const { t } = usePrefs();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<SupportKind>("question");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState(user?.email ?? "");
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<"idle" | "sent" | "error" | "disabled">("idle");
  // null = not asked yet. An instance with RACKMON_SUPPORT_URL unset (or a
  // white-label build) must not show a button that can only ever fail.
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const fabRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let alive = true;
    api
      .supportConfig()
      .then((c) => alive && setEnabled(c.enabled))
      // Never hide the button just because one probe failed: a transient error
      // should not cost a user their way to report the very bug they just hit.
      .catch(() => alive && setEnabled(true));
    return () => {
      alive = false;
    };
  }, []);

  // Close the panel on Escape (keyboard users don't have to shift-Tab to the FAB)
  // and hand focus back to the button, or it lands on <body>.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        fabRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const submit = async () => {
    if (!message.trim() || busy) return;
    setBusy(true);
    setState("idle");
    try {
      await api.sendSupport(message.trim(), email.trim() || undefined, kind);
      setState("sent");
      setMessage("");
      // Each message is classified on its own: leaving the last choice selected
      // silently mis-tags the follow-up (an idea filed as a bug, or the reverse).
      setKind("question");
    } catch (err) {
      // 503 = this instance has no desk configured. Saying "try again" there is a
      // lie: it will never succeed, and the user keeps retrying.
      setState(err instanceof ApiError && err.status === 503 ? "disabled" : "error");
    } finally {
      setBusy(false);
    }
  };

  if (enabled === false) return null;

  const kindLabel = (k: SupportKind) =>
    k === "bug" ? t("supportKindBug") : k === "idea" ? t("supportKindIdea") : t("supportKindQuestion");
  const placeholder =
    kind === "bug"
      ? t("supportPlaceholderBug")
      : kind === "idea"
        ? t("supportPlaceholderIdea")
        : t("supportPlaceholderQuestion");

  return (
    <>
      <button
        ref={fabRef}
        onClick={() => {
          setOpen((o) => !o);
          setState("idle");
          setKind("question"); // reopening starts a fresh report, not the last one's type
        }}
        className="fixed bottom-5 right-5 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-accent text-[color:var(--accent-ink)] shadow-panel transition hover:brightness-110"
        aria-label={t("support")}
        aria-expanded={open}
        aria-controls="support-panel"
        title={t("support")}
        data-testid="support-fab"
      >
        {open ? (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
        )}
      </button>

      {open && (
        <div
          id="support-panel"
          className="fixed bottom-20 right-5 z-40 max-h-[calc(100vh-7rem)] w-[92vw] max-w-sm overflow-y-auto rounded-xl border border-border bg-surface p-4 shadow-panel"
          role="dialog"
          aria-modal="false"
          aria-label={t("supportTitle")}
        >
          <h3 className="mb-1 text-sm font-semibold text-ink">{t("supportTitle")}</h3>
          <p className="mb-3 text-xs text-muted">{t("supportHint")}</p>

          {/* El sitio donde de verdad se trabaja el proyecto. Quien quiera seguir
              el hilo de un fallo, discutirlo o mandar un arreglo, lo hace ahi;
              este formulario es para quien solo quiere contarlo y seguir con su
              dia. Las dos cosas son legitimas, pero solo una deja rastro publico. */}
          <p className="mb-3 text-xs text-muted">
            <a
              className="underline decoration-dotted underline-offset-2 transition-colors hover:text-ink"
              href="https://github.com/rackmonsoftware-star/rackmon/issues"
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("supportGithub")}
            </a>
          </p>

          {state === "sent" ? (
            <div
              className="rounded-md border border-nominal/30 bg-nominal/10 px-3 py-2 text-sm text-nominal"
              data-testid="support-sent"
              role="status"
              aria-live="polite"
            >
              {t("supportSent")}
            </div>
          ) : (
            <div className="space-y-2">
              <div>
                <span className="label" id="support-kind-label">{t("supportKind")}</span>
                <div
                  className="mt-1 flex gap-1.5"
                  role="group"
                  aria-labelledby="support-kind-label"
                  data-testid="support-kind"
                >
                  {KINDS.map((k) => {
                    const active = k === kind;
                    return (
                      <button
                        key={k}
                        type="button"
                        onClick={() => setKind(k)}
                        aria-pressed={active}
                        data-testid={`support-kind-${k}`}
                        className={
                          "flex-1 rounded-md border px-2 py-1.5 text-xs font-medium transition " +
                          // Hover must not borrow the accent, or it reads as selected.
                          (active
                            ? "border-accent bg-accent/15 text-ink ring-1 ring-accent"
                            : "border-border bg-transparent text-muted hover:bg-ink/5 hover:text-ink")
                        }
                      >
                        {kindLabel(k)}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div>
                <label className="label" htmlFor="support-message">{t("supportMessage")}</label>
                <textarea
                  id="support-message"
                  className="input min-h-[96px] resize-y"
                  autoFocus
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder={placeholder}
                  maxLength={5000}
                />
              </div>
              <div>
                <label className="label" htmlFor="support-email">{t("supportEmail")}</label>
                <input
                  id="support-email"
                  className="input"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              {(state === "error" || state === "disabled") && (
                <div
                  className="rounded-md border border-crit/30 bg-crit/10 px-3 py-1.5 text-xs text-crit"
                  role="alert"
                  aria-live="assertive"
                  data-testid="support-error"
                >
                  {state === "disabled" ? t("supportDisabled") : t("supportError")}
                </div>
              )}
              <button
                className="btn-primary w-full"
                onClick={submit}
                disabled={busy || !message.trim()}
                data-testid="support-send"
              >
                {busy ? "…" : t("send")}
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
