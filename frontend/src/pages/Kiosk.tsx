import { useNavigate } from "react-router-dom";

import Overview from "./Overview";
import { usePrefs } from "../prefs";

export default function Kiosk() {
  const navigate = useNavigate();
  const { t } = usePrefs();
  return (
    <div className="min-h-screen p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[15px] font-semibold tracking-tight text-ink">
            Rack<span className="text-accent">Mon</span>
          </span>
          <span className="chip">{t("kiosk")}</span>
        </div>
        <button className="btn-ghost text-xs" aria-label="Exit kiosk" onClick={() => navigate("/")}>
          ✕
        </button>
      </div>
      <Overview />
    </div>
  );
}
