import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth";
import { useBranding } from "../branding";
import { usePrefs } from "../prefs";
import SupportWidget from "./SupportWidget";
import UpdateBanner from "./UpdateBanner";

function ThermalMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden>
      <defs>
        <linearGradient id="mark" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="#38BDF8" />
          <stop offset="45%" stopColor="#34D399" />
          <stop offset="75%" stopColor="#FBBF24" />
          <stop offset="100%" stopColor="#F87171" />
        </linearGradient>
      </defs>
      <rect x="3" y="3" width="20" height="20" rx="5" fill="none" stroke="url(#mark)" strokeWidth="2" />
      <rect x="11" y="7" width="4" height="12" rx="2" fill="url(#mark)" />
    </svg>
  );
}

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span className="mono hidden text-xs text-muted sm:inline">
      {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
    </span>
  );
}

export default function Layout() {
  const { user, logout, can } = useAuth();
  const { t, theme, toggleTheme, lang, setLang } = usePrefs();
  const brand = useBranding();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  const nav = [
    { to: "/", label: t("overview"), end: true },
    { to: "/devices", label: t("devices"), end: false },
    { to: "/alerts", label: t("alerts"), end: false },
    { to: "/reports", label: t("reports"), end: false },
    { to: "/compare", label: t("compare"), end: false },
  ];
  if (can("operator")) nav.push({ to: "/discover", label: t("discover"), end: false });
  if (can("admin")) nav.push({ to: "/admin", label: t("admin"), end: false });

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `shrink-0 whitespace-nowrap px-3 py-2 text-sm rounded-md transition-colors ${
      isActive ? "text-ink bg-surface2" : "text-muted hover:text-ink hover:bg-surface2/60"
    }`;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-border bg-bg/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4">
          <button
            className="flex shrink-0 items-center gap-2"
            onClick={() => navigate("/")}
            aria-label="RackMon home"
          >
            {brand.logo_url ? (
              <img src={brand.logo_url} alt="" className="h-6 w-auto" />
            ) : (
              <ThermalMark />
            )}
            <span className="text-[15px] font-semibold tracking-tight text-ink">
              {brand.product_name === "RackMon" ? (
                <>
                  Rack<span className="text-accent">Mon</span>
                </>
              ) : (
                brand.product_name
              )}
            </span>
          </button>


          <nav className="no-scrollbar ml-2 hidden min-w-0 flex-1 items-center gap-1 overflow-x-auto lg:flex">
            {nav.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={linkClass}>
                {n.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex shrink-0 items-center gap-2 lg:ml-2">
            {/* A partir de lg el menu compite por el ancho con esta zona.
                El reloj es lo primero prescindible. */}
            <div className="hidden xl:block">
              <Clock />
            </div>
            <button
              data-testid="lang-toggle"
              onClick={() => setLang(lang === "en" ? "es" : "en")}
              className="btn-ghost px-2 py-1 text-xs mono"
              title="Language"
            >
              {lang.toUpperCase()}
            </button>
            <button
              data-testid="theme-toggle"
              onClick={toggleTheme}
              className="btn-ghost px-2 py-1"
              title="Theme"
              aria-label="Toggle theme"
            >
              {theme === "dark" ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
                </svg>
              )}
            </button>
            <button
              data-testid="kiosk-btn"
              onClick={() => navigate("/kiosk")}
              className="btn-ghost px-2 py-1 text-xs"
              title={t("kiosk")}
              aria-label={t("kiosk")}
            >
              ⛶
            </button>
            <div className="mx-1 hidden h-6 w-px bg-border sm:block" />
            <button
              data-testid="profile-link"
              onClick={() => navigate("/profile")}
              className="hidden text-right sm:block hover:opacity-80"
              title={t("profile")}
            >
              <div className="hidden text-xs text-ink xl:block">{user?.email}</div>
              <div className="text-[10px] uppercase tracking-wide text-muted">{user?.role}</div>
            </button>
            <button data-testid="logout-btn" onClick={() => logout()} className="hidden btn-ghost text-xs sm:inline-flex" title={t("logout")}>
              {t("logout")}
            </button>
            <button
              data-testid="menu-toggle"
              onClick={() => setMenuOpen((o) => !o)}
              className="btn-ghost px-2 py-1 lg:hidden"
              aria-label="Menu"
              aria-expanded={menuOpen}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                {menuOpen ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
              </svg>
            </button>
          </div>
        </div>

        {menuOpen && (
          <nav className="border-t border-border bg-bg/95 px-4 py-2 lg:hidden" aria-label="Mobile">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `block rounded-md px-3 py-2.5 text-sm ${
                    isActive ? "bg-surface2 text-ink" : "text-muted hover:bg-surface2/60 hover:text-ink"
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
            <div className="mt-2 flex items-center justify-between border-t border-border px-3 pt-3">
              <button onClick={() => navigate("/profile")} className="text-left">
                <div className="text-xs text-ink">{user?.email}</div>
                <div className="text-[10px] uppercase tracking-wide text-muted">{user?.role}</div>
              </button>
              <button onClick={() => logout()} className="btn-ghost text-xs">
                {t("logout")}
              </button>
            </div>
          </nav>
        )}
      </header>

      <UpdateBanner />

      {/* pb-24 en móvil: el botón flotante de feedback es fijo y, sin este hueco,
          se queda encima de la última fila de las tablas — que son pulsables, así
          que un toque ahí abría el feedback en vez del dispositivo. */}
      <main className="mx-auto max-w-7xl space-y-4 px-4 py-6 pb-24 sm:pb-6">
        <Outlet />
      </main>

      <SupportWidget />
    </div>
  );
}
