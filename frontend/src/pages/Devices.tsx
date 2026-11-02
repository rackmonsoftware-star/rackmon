import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import StatusBadge from "../components/StatusBadge";
import { useAuth } from "../auth";
import { usePoll } from "../hooks";
import { usePrefs } from "../prefs";
import { escalaDe, formatTemp, thermalTextColor, timeAgo } from "../lib/thermal";
import type { Device, DeviceStatus, DeviceStatusKind } from "../types";

export default function Devices() {
  const { t, theme } = usePrefs();
  const light = theme === "light";
  const { can } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [rackFilter, setRackFilter] = useState("all");
  const [sortKey, setSortKey] = useState<"name" | "rack" | "status" | "temp" | "lastSeen">("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const pageSize = 15;

  const { data: devices, refetch } = usePoll(() => api.devices(), 8000);
  const { data: statuses } = usePoll(api.statuses, 8000);

  const statusById = useMemo(() => {
    const m = new Map<number, DeviceStatus>();
    (statuses ?? []).forEach((s) => m.set(s.device.id, s));
    return m;
  }, [statuses]);

  const kindOf = (d: Device): DeviceStatusKind =>
    d.in_maintenance ? "maintenance" : statusById.get(d.id)?.status ?? "nodata";

  const racks = useMemo(
    () => Array.from(new Set((devices ?? []).map((d) => d.rack).filter(Boolean))) as string[],
    [devices],
  );

  const filtered = useMemo(() => {
    let list = devices ?? [];
    const q = query.trim().toLowerCase();
    if (q)
      list = list.filter(
        (d) =>
          d.name.toLowerCase().includes(q) ||
          d.ip.includes(q) ||
          (d.rack ?? "").toLowerCase().includes(q) ||
          d.tags.some((tag) => tag.toLowerCase().includes(q)),
      );
    if (statusFilter !== "all") list = list.filter((d) => kindOf(d) === statusFilter);
    if (rackFilter !== "all") list = list.filter((d) => d.rack === rackFilter);
    const dir = sortDir === "asc" ? 1 : -1;
    const val = (d: Device): string | number => {
      switch (sortKey) {
        case "rack": return `${d.rack ?? ""}${String(d.position_u ?? 0).padStart(3, "0")}`;
        case "status": return kindOf(d);
        case "temp": return statusById.get(d.id)?.temperature ?? -999;
        case "lastSeen": return statusById.get(d.id)?.last_seen ?? "";
        default: return d.name.toLowerCase();
      }
    };
    return [...list].sort((a, b) => {
      const va = val(a), vb = val(b);
      return va < vb ? -dir : va > vb ? dir : 0;
    });
  }, [devices, query, statusFilter, rackFilter, sortKey, sortDir, statusById]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const paged = filtered.slice(page * pageSize, page * pageSize + pageSize);
  useEffect(() => {
    if (page >= pageCount) setPage(0);
  }, [pageCount, page]);

  const toggleSort = (k: typeof sortKey) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir("asc");
    }
  };
  const sortArrow = (k: typeof sortKey) => (sortKey === k ? (sortDir === "asc" ? " ▲" : " ▼") : "");
  // Sortable column header: stays a columnheader (keeps table semantics), but is
  // keyboard-focusable/operable and exposes the current sort via aria-sort.
  const sortTh = (k: typeof sortKey, label: string, cls = "") => (
    <th
      className={`cursor-pointer select-none px-4 py-3 font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/50 ${cls}`}
      onClick={() => toggleSort(k)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleSort(k);
        }
      }}
      tabIndex={0}
      aria-sort={sortKey === k ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
    >
      {label}
      {sortArrow(k)}
    </th>
  );
  const toggleSel = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const allOnPageSelected = paged.length > 0 && paged.every((d) => selected.has(d.id));
  const toggleSelAll = () =>
    setSelected((s) => {
      const n = new Set(s);
      if (allOnPageSelected) paged.forEach((d) => n.delete(d.id));
      else paged.forEach((d) => n.add(d.id));
      return n;
    });
  const bulkDelete = async () => {
    if (!window.confirm(`${t("deleteSelected")} (${selected.size})?`)) return;
    const results = await Promise.allSettled(
      Array.from(selected).map((id) => api.deleteDevice(id)),
    );
    setSelected(new Set());
    refetch();
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed) window.alert(`${failed}/${results.length} could not be deleted (check your permissions).`);
  };
  const bulkMaintenance = async () => {
    const results = await Promise.allSettled(
      Array.from(selected).map((id) => api.setMaintenance(id, 120)),
    );
    setSelected(new Set());
    refetch();
    const failed = results.filter((r) => r.status === "rejected").length;
    if (failed) window.alert(`${failed}/${results.length} could not be updated (check your permissions).`);
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">{t("devices")}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="input w-56"
            aria-label={t("search")}
            placeholder={t("search")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            data-testid="status-filter"
            aria-label={t("allStatuses")}
            className="input w-40"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">{t("allStatuses")}</option>
            <option value="ok">{t("nominal")}</option>
            <option value="warning">{t("warning")}</option>
            <option value="critical">{t("critical")}</option>
            <option value="maintenance">{t("maintenance")}</option>
            <option value="nodata">{t("noData")}</option>
          </select>
          <select
            data-testid="rack-filter"
            aria-label={t("allRacks")}
            className="input w-36"
            value={rackFilter}
            onChange={(e) => setRackFilter(e.target.value)}
          >
            <option value="all">{t("allRacks")}</option>
            {racks.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          {can("operator") && (
            <button className="btn-primary whitespace-nowrap" onClick={() => setShowCreate(true)}>
              + {t("addDevice")}
            </button>
          )}
        </div>
      </div>

      {can("operator") && selected.size > 0 && (
        <div className="panel flex items-center gap-3 px-4 py-2 text-sm" data-testid="bulk-bar">
          <span className="font-medium">{selected.size} {t("selectedCount")}</span>
          <button data-testid="bulk-maintenance" className="btn-ghost text-xs" onClick={bulkMaintenance}>
            {t("enterMaintenance")}
          </button>
          <button data-testid="bulk-delete" className="btn-ghost text-xs text-crit" onClick={bulkDelete}>
            {t("deleteSelected")}
          </button>
          <button className="btn-ghost text-xs" onClick={() => setSelected(new Set())}>
            {t("cancel")}
          </button>
        </div>
      )}

      <div className="panel overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
              {can("operator") && (
                <th className="px-4 py-3" aria-label="Select">
                  <input type="checkbox" aria-label={t("selectAll")} data-testid="select-all" checked={allOnPageSelected} onChange={toggleSelAll} />
                </th>
              )}
              {sortTh("name", t("name"))}
              <th className="px-4 py-3 font-medium">{t("ip")}</th>
              {sortTh("rack", t("rack"))}
              {sortTh("status", t("status"))}
              {sortTh("temp", t("temperature"), "text-right")}
              {sortTh("lastSeen", t("lastSeen"))}
              <th className="px-4 py-3 font-medium">{t("tags")}</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((d) => {
              const st = statusById.get(d.id);
              const kind: DeviceStatusKind = d.in_maintenance
                ? "maintenance"
                : st?.status ?? "nodata";
              return (
                <tr
                  key={d.id}
                  onClick={() => navigate(`/devices/${d.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      navigate(`/devices/${d.id}`);
                    }
                  }}
                  tabIndex={0}
                  role="link"
                  aria-label={d.name}
                  className="cursor-pointer border-b border-border/60 transition-colors hover:bg-surface2/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/50"
                >
                  {can("operator") && (
                    <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${d.name}`}
                        className="device-check"
                        checked={selected.has(d.id)}
                        onChange={() => toggleSel(d.id)}
                      />
                    </td>
                  )}
                  <td className="px-4 py-3">
                    <div className="whitespace-nowrap font-medium text-ink">{d.name}</div>
                    {d.vendor && <div className="text-xs text-muted">{d.vendor}</div>}
                  </td>
                  <td className="px-4 py-3 mono text-muted">{d.ip}</td>
                  <td className="px-4 py-3 whitespace-nowrap text-muted">
                    {d.rack ? `${d.rack}${d.position_u ? ` · U${d.position_u}` : ""}` : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={kind} />
                  </td>
                  <td className="px-4 py-3 text-right mono" style={{ color: thermalTextColor(st?.temperature, light, escalaDe(st?.temperature_metric)) }}>
                    {formatTemp(st?.temperature)}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">{timeAgo(st?.last_seen ?? null)}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {d.tags.slice(0, 3).map((tag) => (
                        <span key={tag} className="chip">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={can("operator") ? 8 : 7} className="px-4 py-10 text-center text-sm text-muted">
                  {devices ? t("noDevices") : t("loading")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {pageCount > 1 && (
        <div className="flex items-center justify-between text-sm text-muted">
          <span>{filtered.length} · {statusFilter === "all" && rackFilter === "all" ? "" : "filtered"}</span>
          <div className="flex items-center gap-2">
            <button className="btn-ghost" aria-label="Previous page" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
              ‹
            </button>
            <span>{page + 1} / {pageCount}</span>
            <button data-testid="next-page" className="btn-ghost" aria-label="Next page" disabled={page >= pageCount - 1} onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}>
              ›
            </button>
          </div>
        </div>
      )}

      {showCreate && (
        <CreateDeviceModal
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            refetch();
          }}
        />
      )}
    </div>
  );
}

function CreateDeviceModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = usePrefs();
  const [form, setForm] = useState({
    name: "",
    ip: "",
    snmp_version: "2c",
    snmp_community: "public",
    vendor: "",
    rack: "",
    position_u: "",
    tags: "",
  });
  const [template, setTemplate] = useState("");
  const [templates, setTemplates] = useState<Array<{ name: string; vendor: string }>>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.templates().then((list) => setTemplates(list)).catch(() => undefined);
  }, []);

  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const tags = form.tags
        ? form.tags.split(",").map((s) => s.trim()).filter(Boolean)
        : [];
      if (template) {
        // Template supplies the metric catalog; vendor comes from the template.
        await api.applyTemplate({
          template,
          name: form.name,
          ip: form.ip,
          community: form.snmp_community || "public",
          snmp_version: form.snmp_version,
          rack: form.rack || undefined,
          position_u: form.position_u ? Number(form.position_u) : undefined,
          tags,
        });
      } else {
        await api.createDevice({
          name: form.name,
          ip: form.ip,
          snmp_version: form.snmp_version,
          snmp_community: form.snmp_community || undefined,
          vendor: form.vendor || undefined,
          rack: form.rack || undefined,
          position_u: form.position_u ? Number(form.position_u) : undefined,
          tags,
        });
      }
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create device");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" className="panel w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-base font-semibold">{t("addDevice")}</h3>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="label">{t("template")}</label>
              <select aria-label={t("template")} className="input" value={template} onChange={(e) => setTemplate(e.target.value)}>
                <option value="">{t("none")}</option>
                {templates.map((tp) => (
                  <option key={tp.name} value={tp.name}>
                    {tp.name} ({tp.vendor})
                  </option>
                ))}
              </select>
            </div>
            <div className="col-span-2">
              <label className="label">{t("name")}</label>
              <input aria-label={t("name")} className="input" value={form.name} onChange={(e) => set("name", e.target.value)} required autoFocus />
            </div>
            <div>
              <label className="label">{t("ip")}</label>
              <input aria-label={t("ip")} className="input mono" value={form.ip} onChange={(e) => set("ip", e.target.value)} required placeholder="10.0.0.1" />
            </div>
            <div>
              <label className="label">{t("version")}</label>
              <select aria-label={t("version")} className="input" value={form.snmp_version} onChange={(e) => set("snmp_version", e.target.value)}>
                <option value="2c">v2c</option>
                <option value="1">v1</option>
                <option value="3">v3</option>
              </select>
            </div>
            <div>
              <label className="label">{t("community")}</label>
              <input aria-label={t("community")} className="input mono" value={form.snmp_community} onChange={(e) => set("snmp_community", e.target.value)} />
            </div>
            <div>
              <label className="label">{t("vendor")}</label>
              <input aria-label={t("vendor")} className="input" value={form.vendor} onChange={(e) => set("vendor", e.target.value)} placeholder="Dell / HP / …" />
            </div>
            <div>
              <label className="label">{t("rack")}</label>
              <input aria-label={t("rack")} className="input" value={form.rack} onChange={(e) => set("rack", e.target.value)} placeholder="RACK-A" />
            </div>
            <div>
              <label className="label">{t("position")}</label>
              <input aria-label={t("position")} className="input mono" type="number" min={1} max={60} value={form.position_u} onChange={(e) => set("position_u", e.target.value)} />
            </div>
            <div className="col-span-2">
              <label className="label">{t("tags")}</label>
              <input aria-label={t("tags")} className="input" value={form.tags} onChange={(e) => set("tags", e.target.value)} placeholder="compute, prod" />
            </div>
          </div>

          {error && (
            <div className="rounded-md border border-crit/30 bg-crit/10 px-3 py-2 text-sm text-crit">{error}</div>
          )}

          <div className="flex justify-end gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>
              {t("cancel")}
            </button>
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy ? "…" : t("create")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
