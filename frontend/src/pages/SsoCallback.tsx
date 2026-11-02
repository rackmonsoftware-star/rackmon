import { useEffect, useState } from "react";

import { setTokens } from "../api";
import { usePrefs } from "../prefs";

/**
 * Donde aterriza el navegador al volver del proveedor de identidad.
 *
 * Esta pantalla no existía, y por eso el SSO —función de pago, y de las más
 * anunciadas— no podía completar un inicio de sesión. El proveedor redirigía la
 * ventana entera al backend, el backend contestaba con un JSON, y ahí se
 * acababa todo: el usuario veía sus propios tokens en crudo sobre fondo blanco
 * y la aplicación nunca se enteraba de nada.
 *
 * Los tokens llegan en el fragmento (#) justamente para que no viajen al
 * servidor ni a terceros por la cabecera Referer. Se guardan y se borran de la
 * barra de direcciones en el acto, antes de nada más.
 */
export default function SsoCallback() {
  const { t } = usePrefs();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, "");
    const p = new URLSearchParams(hash);
    const access = p.get("access_token");
    const refresh = p.get("refresh_token");

    // Lo primero, siempre: que los tokens dejen de estar en la barra de
    // direcciones, la haya leído alguien por encima del hombro o no.
    try {
      window.history.replaceState(null, "", window.location.pathname);
    } catch {
      /* da igual: no es la parte que importa */
    }

    if (!access || !refresh) {
      setError(p.get("error") || t("ssoNoTokens"));
      return;
    }
    setTokens({ access_token: access, refresh_token: refresh, token_type: "bearer" });
    // Recarga completa a propósito: así el proveedor de sesión arranca de cero y
    // lee la sesión recién guardada, sin tener que coordinar nada entre ambos.
    window.location.replace("/");
  }, [t]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-sm text-crit">{error}</p>
        <a className="btn" href="/login">
          {t("backToLogin")}
        </a>
      </div>
    );
  }
  return (
    <div className="flex min-h-screen items-center justify-center text-sm text-muted">
      {t("signingIn")}
    </div>
  );
}
