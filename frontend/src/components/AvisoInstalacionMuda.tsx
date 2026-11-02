import { useNavigate } from "react-router-dom";

import { usePrefs } from "../prefs";

/**
 * Avisa cuando esta instalación no puede avisar de nada.
 *
 * Dos formas de estar muda, y las dos se han dado de verdad en producción:
 *
 *  - Sin reglas de alerta, el motor no dispara nunca. Una instalación limpia
 *    arrancaba así hasta la 1.2.5, y lo recomendaban nuestros propios docs.
 *  - Sin ningún canal configurado, un disparo solo deja una línea en un log
 *    que no lee nadie. La consola siempre dice «enviado», así que ni siquiera
 *    el registro de notificaciones delata el problema.
 *
 * En los dos casos el panel pinta tarjetas rojas y parece que todo funciona.
 * Ese es justo el motivo por el que hay que decirlo en portada y no esconderlo
 * en una pantalla de ajustes que nadie visita.
 */
export default function AvisoInstalacionMuda({
  reglas,
  canales,
  demo,
}: {
  reglas: number | undefined;
  canales: number | undefined;
  demo?: boolean;
}) {
  const { t } = usePrefs();
  const navigate = useNavigate();

  // En la demo pública no hay a quién notificar por diseño, así que este aviso
  // no informaría de nada: solo sería lo primero que ve, en ámbar y con pinta de
  // defecto, alguien que acaba de pulsar "Ver demo en vivo" desde la web.
  if (demo) return null;

  // undefined = el backend no lo manda (versión anterior): no inventamos nada.
  const sinReglas = reglas === 0;
  const sinCanales = reglas !== undefined && canales === 0;
  if (!sinReglas && !sinCanales) return null;

  const texto = sinReglas ? t("muteNoRules") : t("muteNoChannels");
  const destino = sinReglas ? "/alerts" : "/admin";
  const color = sinReglas ? "#F87171" : "#FBBF24";

  return (
    <div
      role="alert"
      className="flex items-center gap-3 rounded-md px-4 py-2 text-sm text-ink"
      style={{ border: `1px solid ${color}66`, background: `${color}14` }}
    >
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
      <span className="min-w-0 flex-1">{texto}</span>
      <button className="shrink-0 underline hover:opacity-80" onClick={() => navigate(destino)}>
        {t("muteFix")}
      </button>
    </div>
  );
}
