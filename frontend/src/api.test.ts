import { describe, expect, it } from "vitest";

import { api } from "./api";

describe("api URL builders", () => {
  it("builds a CSV export URL", () => {
    expect(api.exportUrl(3, "temp_cpu", "csv")).toBe(
      "/api/v1/metrics/export?device_id=3&metric=temp_cpu&fmt=csv",
    );
  });

  it("builds a report PDF URL with range", () => {
    const url = api.reportPdfUrl("2024-01-01T00:00:00.000Z", "2024-01-08T00:00:00.000Z");
    expect(url).toContain("/api/v1/reports/adhoc?");
    expect(url).toContain("fmt=pdf");
    expect(url).toContain("from=2024-01-01");
    expect(url).toContain("to=2024-01-08");
  });

  it("encodes device ids in the report URL when provided", () => {
    const url = api.reportPdfUrl("2024-01-01T00:00:00.000Z", "2024-01-08T00:00:00.000Z", [1, 2, 3]);
    expect(url).toContain("device_ids=1%2C2%2C3");
  });
});
