import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import LineChart from "./LineChart";

const now = Date.now();
const samples = Array.from({ length: 6 }, (_, i) => ({
  t: new Date(now - (6 - i) * 60_000).toISOString(),
  v: 30 + i * 5,
}));

describe("LineChart", () => {
  it("renders an svg with a line for samples", () => {
    const { container } = render(<LineChart samples={samples} unit="°C" warn={60} crit={75} />);
    expect(container.querySelector("svg")).toBeTruthy();
    expect(container.querySelectorAll("path").length).toBeGreaterThan(0);
  });
  it("shows an empty state with no samples", () => {
    render(<LineChart samples={[]} />);
    expect(screen.getByText(/No data in range/i)).toBeInTheDocument();
  });
});
