import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import RackElevation from "./RackElevation";
import type { DeviceStatus } from "../types";

function ds(id: number, rack: string | null, pos: number | null, temp: number | null, status: DeviceStatus["status"]): DeviceStatus {
  return {
    device: {
      id, name: `dev-${id}`, hostname: null, ip: `10.0.0.${id}`, snmp_version: "2c",
      snmp_port: 161, vendor: null, model: null, rack, position_u: pos, size_u: 1,
      tags: [], enabled: true, has_community: true, in_maintenance: false,
      created_at: new Date().toISOString(), metrics: [],
    },
    status, temperature: temp, last_seen: new Date().toISOString(), firing_alerts: 0,
  };
}

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("RackElevation", () => {
  it("renders racks and an unplaced group", () => {
    wrap(<RackElevation statuses={[
      ds(1, "RACK-A", 40, 32, "ok"),
      ds(2, "RACK-A", 10, 78, "critical"),
      ds(3, null, null, 40, "ok"),
    ]} />);
    expect(screen.getByText("RACK-A")).toBeInTheDocument();
    expect(screen.getByText("Unplaced")).toBeInTheDocument();
    // Temperatures are rendered on the blocks.
    expect(screen.getByText("32.0°")).toBeInTheDocument();
  });

  it("shows a message when there are no devices", () => {
    const { container } = wrap(<RackElevation statuses={[]} />);
    expect(container.textContent).toMatch(/No devices/i);
  });
});
