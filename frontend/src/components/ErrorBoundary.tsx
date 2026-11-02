import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/**
 * Catches any render-time error anywhere below it so a single component bug can
 * never white-screen the whole app. The user gets a friendly panel and a reload
 * button; the error is logged for diagnostics. Styles are inline so this renders
 * even if the stylesheet itself failed to load.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("RackMon render error:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0B0F14",
          color: "#E5E7EB",
          fontFamily: "Inter, system-ui, -apple-system, sans-serif",
          padding: 24,
        }}
      >
        <div style={{ maxWidth: 460, textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
          <h1 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>Something went wrong</h1>
          <p style={{ fontSize: 14, color: "#9CA3AF", marginBottom: 20, lineHeight: 1.5 }}>
            The interface hit an unexpected error. Your data is safe — reloading usually fixes it.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              background: "#22D3EE",
              color: "#0B0F14",
              border: "none",
              borderRadius: 8,
              padding: "8px 22px",
              fontSize: 14,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Reload
          </button>
          <pre
            style={{
              marginTop: 16,
              fontSize: 11,
              color: "#6B7280",
              whiteSpace: "pre-wrap",
              textAlign: "left",
              maxHeight: 120,
              overflow: "auto",
            }}
          >
            {String(this.state.error?.message || "")}
          </pre>
        </div>
      </div>
    );
  }
}
