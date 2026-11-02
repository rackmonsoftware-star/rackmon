import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import Sparkline from "./Sparkline";

describe("Sparkline", () => {
  it("draws a path for multiple values", () => {
    const { container } = render(<Sparkline values={[1, 5, 2, 8, 3]} />);
    expect(container.querySelector("svg")).toBeTruthy();
    expect(container.querySelector("path")).toBeTruthy();
  });
  it("renders an empty svg for too few values", () => {
    const { container } = render(<Sparkline values={[1]} />);
    expect(container.querySelector("svg")).toBeTruthy();
    expect(container.querySelector("path")).toBeNull();
  });
});
