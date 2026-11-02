import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, clearTokens, hasSession } from "./api";
import type { Role, User } from "./types";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string, otp?: string) => Promise<void>;
  loginLdap: (username: string, password: string) => Promise<void>;
  loginDemo: () => Promise<void>;
  logout: () => Promise<void>;
  can: (role: Role) => boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

const RANK: Record<Role, number> = { viewer: 1, operator: 2, admin: 3 };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const loadMe = useCallback(async () => {
    if (!hasSession()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      clearTokens();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMe();
    const onLogout = () => setUser(null);
    window.addEventListener("rackmon:logout", onLogout);
    return () => window.removeEventListener("rackmon:logout", onLogout);
  }, [loadMe]);

  const login = useCallback(async (email: string, password: string, otp?: string) => {
    await api.login(email, password, otp);
    setUser(await api.me());
  }, []);

  const loginLdap = useCallback(async (username: string, password: string) => {
    await api.ldapLogin(username, password);
    setUser(await api.me());
  }, []);

  // Demo pública: entra sin credenciales. El servidor sólo lo permite con
  // RACKMON_DEMO_MODE=true y sólo entrega una cuenta de solo lectura.
  const loginDemo = useCallback(async () => {
    await api.demoLogin();
    setUser(await api.me());
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
    // En la demo pública la pantalla de login entra sola. Sin esta marca,
    // cerrar sesión te devolvería dentro al instante: un bucle del que no se
    // puede salir. Dura lo que la pestaña.
    try { sessionStorage.setItem("rm_demo_exit", "1"); } catch { /* modo privado */ }
  }, []);

  const can = useCallback(
    (role: Role) => (user ? RANK[user.role] >= RANK[role] : false),
    [user],
  );

  const value = useMemo(
    () => ({ user, loading, login, loginLdap, loginDemo, logout, can }),
    [user, loading, login, loginLdap, loginDemo, logout, can],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
