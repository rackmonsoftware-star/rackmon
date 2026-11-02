import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { ApiError } from "./api";
import { AuthProvider } from "./auth";
import { BrandingProvider } from "./branding";
import ErrorBoundary from "./components/ErrorBoundary";
import { PrefsProvider } from "./prefs";
import "./index.css";

// Safety net: surface API errors from fire-and-forget mutation handlers that don't
// catch them, so failed actions aren't silent. (401s are handled by the auth flow.)
window.addEventListener("unhandledrejection", (e) => {
  if (e.reason instanceof ApiError && e.reason.status !== 401) {
    e.preventDefault();
    window.alert(e.reason.message || "Something went wrong — please try again.");
  }
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <BrandingProvider>
        <PrefsProvider>
          <BrowserRouter>
            <AuthProvider>
              <App />
            </AuthProvider>
          </BrowserRouter>
        </PrefsProvider>
      </BrandingProvider>
    </ErrorBoundary>
  </StrictMode>,
);
