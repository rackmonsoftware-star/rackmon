import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { usePrefs } from "../prefs";

type Found = Awaited<ReturnType<typeof api.discoveryScan>>[number];

export default function Discover() {
  const { t } = usePrefs();
  const navigate = useNavigate();
  const [target, setTarget] = useState("10.0.0.0/28");
  const [community, setCommunity] = useState("public");
  const [version, setVersion] = useState("2c");
  const [results, setResults] = useState<Found[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const scan = async () => {
    setBusy(true);
    setError(null);
    setMsg(null);
    setSelected(new Set());
    try {
      setResults(await api.discoveryScan(target, community, version));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setBusy(false);
    }
  };

  const toggle = (ip: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(ip) ? next.delete(ip) : next.add(ip);
      return next;
    });
  };

  const importSelected = async () => {
    // El escaneo YA deduce el fabricante del sysDescr y lo enseña en la columna
    // "Vendor" de esta misma tabla — pero no se mandaba al importar, así que el
    // servidor creaba cada equipo sin fabricante y le ponía el catálogo genérico.
    // El cliente que importa cuarenta equipos de cinco marcas seguía sin recibir
    // el catálogo de la suya: el equipo quedaba creado, habilitado y mudo.
    const porIp = new Map((results ?? []).map((r) => [r.ip, r]));
    const devices = [...selected].map((ip) => {
      const encontrado = porIp.get(ip);
      return {
        ip,
        community,
        snmp_version: version,
        name: encontrado?.sysname || undefined,
        vendor: encontrado?.vendor || undefined,
      };
    });
    if (devices.length === 0) return;
    setBusy(true);
    try {
      const res = await api.discoveryImport(devices);
      setMsg(
        `${res.created.length} ${res.created.length === 1 ? "device" : "devices"} imported` +
          (res.skipped.length ? `, ${res.skipped.length} skipped` : ""),
      );
      await scan();
    } finally {
      setBusy(false);
    }
  };

  const selectable = (results ?? []).filter((r) => !r.already_known);

  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">{t("discover")}</h2>

      <div className="panel flex flex-wrap items-end gap-4 p-4">
        <div className="min-w-[16rem] flex-1">
          <label className="label">{t("target")}</label>
          <input aria-label={t("target")} className="input mono" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="10.0.0.0/24" />
        </div>
        <div>
          <label className="label">{t("community")}</label>
          <input aria-label={t("community")} className="input mono w-36" value={community} onChange={(e) => setCommunity(e.target.value)} />
        </div>
        <div>
          <label className="label">{t("version")}</label>
          <select aria-label={t("version")} className="input w-24" value={version} onChange={(e) => setVersion(e.target.value)}>
            <option value="2c">v2c</option>
            <option value="1">v1</option>
            <option value="3">v3</option>
          </select>
        </div>
        <button className="btn-primary" onClick={scan} disabled={busy}>
          {busy ? "…" : t("scan")}
        </button>
      </div>

      {error && (
        <div className="rounded-md border border-crit/30 bg-crit/10 px-3 py-2 text-sm text-crit">{error}</div>
      )}
      {msg && (
        <div className="rounded-md border border-nominal/30 bg-nominal/10 px-3 py-2 text-sm text-nominal">{msg}</div>
      )}

      {results && (
        <div className="panel overflow-x-auto">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="text-sm text-muted">
              {results.length} {results.length === 1 ? "host" : "hosts"}
            </span>
            <button
              className="btn-primary text-xs"
              onClick={importSelected}
              disabled={busy || selected.size === 0}
            >
              {t("importSelected")} ({selected.size})
            </button>
          </div>
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted">
                <th className="w-10 px-4 py-3">
                  <input
                    type="checkbox"
                    checked={selectable.length > 0 && selected.size === selectable.length}
                    onChange={(e) =>
                      setSelected(e.target.checked ? new Set(selectable.map((r) => r.ip)) : new Set())
                    }
                  />
                </th>
                <th className="px-4 py-3 font-medium">{t("ip")}</th>
                <th className="px-4 py-3 font-medium">{t("name")}</th>
                <th className="px-4 py-3 font-medium">{t("vendor")}</th>
                <th className="px-4 py-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.ip} className="border-b border-border/60">
                  <td className="px-4 py-2.5">
                    <input
                      type="checkbox"
                      disabled={r.already_known}
                      checked={selected.has(r.ip)}
                      onChange={() => toggle(r.ip)}
                    />
                  </td>
                  <td className="px-4 py-2.5 mono text-ink">{r.ip}</td>
                  <td className="px-4 py-2.5 text-muted">{r.sysname ?? "—"}</td>
                  <td className="px-4 py-2.5 text-muted">{r.vendor ?? "—"}</td>
                  <td className="px-4 py-2.5 text-right">
                    {r.already_known && <span className="chip text-nominal">{t("alreadyAdded")}</span>}
                  </td>
                </tr>
              ))}
              {results.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-sm text-muted">
                    {t("noData")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex justify-end">
        <button
          className="inline-flex items-center gap-1 text-sm text-accent hover:underline"
          onClick={() => navigate("/devices")}
        >
          {t("manageDevices")} <span aria-hidden>→</span>
        </button>
      </div>
    </div>
  );
}
