import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import MultiLineChart from "./MultiLineChart";

const now = Date.now();
const mk = (base: number) =>
  Array.from({ length: 5 }, (_, i) => ({ t: new Date(now - (5 - i) * 60_000).toISOString(), v: base + i }));

describe("MultiLineChart", () => {
  it("draws a line and legend per series", () => {
    const { container } = render(
      <MultiLineChart
        series={[
          { name: "dev-a", color: "#22D3EE", samples: mk(30) },
          { name: "dev-b", color: "#F87171", samples: mk(50) },
        ]}
        unit="°C"
      />,
    );
    expect(container.querySelectorAll("path").length).toBe(2);
    expect(screen.getByText("dev-a")).toBeInTheDocument();
    expect(screen.getByText("dev-b")).toBeInTheDocument();
  });

  it("prompts when there is nothing to compare", () => {
    render(<MultiLineChart series={[]} />);
    expect(screen.getByText(/Select devices/i)).toBeInTheDocument();
  });
});
