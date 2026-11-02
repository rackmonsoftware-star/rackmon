import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import StatusBadge from "./StatusBadge";
import { PrefsProvider } from "../prefs";

const wrap = (ui: React.ReactNode) => render(<PrefsProvider>{ui}</PrefsProvider>);

describe("StatusBadge variants", () => {
  it("renders each status label", () => {
    wrap(<StatusBadge status="ok" />);
    expect(screen.getByText("Nominal")).toBeInTheDocument();
    wrap(<StatusBadge status="maintenance" />);
    expect(screen.getByText("Maintenance")).toBeInTheDocument();
    wrap(<StatusBadge status="nodata" />);
    expect(screen.getByText("No data")).toBeInTheDocument();
  });
});
