import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { useAuth } from "./auth";
import { usePrefs } from "./prefs";
import Admin from "./pages/Admin";
import Alerts from "./pages/Alerts";
import Compare from "./pages/Compare";
import DeviceDetail from "./pages/DeviceDetail";
import Devices from "./pages/Devices";
import Discover from "./pages/Discover";
import Kiosk from "./pages/Kiosk";
import Profile from "./pages/Profile";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Reports from "./pages/Reports";
import SsoCallback from "./pages/SsoCallback";
import StatusPage from "./pages/StatusPage";

function FullScreenLoader() {
  const { t } = usePrefs();
  return (
    <div className="flex min-h-screen items-center justify-center text-sm text-muted">
      {t("loading")}
    </div>
  );
}

/** Redirects to the dashboard if the user lacks the required role. */
function RequireRole({ role, children }: { role: "operator" | "admin"; children: React.ReactNode }) {
  const { can } = useAuth();
  return can(role) ? <>{children}</> : <Navigate to="/" replace />;
}

export default function App() {
  const { user, loading } = useAuth();

  if (loading) return <FullScreenLoader />;

  if (!user) {
    return (
      <Routes>
        {/* Public, unauthenticated status board. */}
        <Route path="/status" element={<StatusPage />} />
        <Route path="/login" element={<Login />} />
        {/* La vuelta del proveedor de identidad. Va en la rama SIN sesión a
            propósito: cuando el navegador llega aquí todavía no hay sesión —
            es precisamente esta pantalla la que la guarda. Si estuviera solo
            en la rama con sesión, el comodín de abajo la mandaría a /login y
            el SSO no podría completarse nunca. */}
        <Route path="/auth/callback" element={<SsoCallback />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/status" element={<StatusPage />} />
      <Route path="/kiosk" element={<Kiosk />} />
      <Route path="/auth/callback" element={<Navigate to="/" replace />} />
      <Route element={<Layout />}>
        <Route path="/" element={<Overview />} />
        <Route path="/devices" element={<Devices />} />
        <Route path="/devices/:id" element={<DeviceDetail />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/compare" element={<Compare />} />
        <Route path="/discover" element={<RequireRole role="operator"><Discover /></RequireRole>} />
        <Route path="/admin" element={<RequireRole role="admin"><Admin /></RequireRole>} />
        <Route path="/profile" element={<Profile />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
