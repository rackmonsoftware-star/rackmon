import { describe, expect, it } from "vitest";
import { act, render, renderHook, screen } from "@testing-library/react";

import StatusBadge from "./components/StatusBadge";
import { PrefsProvider, usePrefs } from "./prefs";

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <PrefsProvider>{children}</PrefsProvider>
);

describe("StatusBadge", () => {
  it("renders the localized label for a status", () => {
    render(<StatusBadge status="critical" />, { wrapper });
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });
});

describe("prefs i18n", () => {
  it("defaults to English and switches to Spanish", () => {
    const { result } = renderHook(() => usePrefs(), { wrapper });
    expect(result.current.t("overview")).toBe("Overview");
    act(() => result.current.setLang("es"));
    expect(result.current.t("overview")).toBe("Resumen");
  });

  it("toggles the theme", () => {
    const { result } = renderHook(() => usePrefs(), { wrapper });
    const first = result.current.theme;
    act(() => result.current.toggleTheme());
    expect(result.current.theme).not.toBe(first);
  });
});
