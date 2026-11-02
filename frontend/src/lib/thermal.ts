import type { DeviceStatusKind, Severity } from "../types";

/**
 * El color de una temperatura tiene que significar LO MISMO que su estado.
 *
 * Antes había una sola rampa, de 15 a 90 °C, descrita en su propio comentario
 * como "server-inlet/CPU range": mezclaba las dos cosas. Mientras el panel
 * enseñaba temperaturas de CPU (30-75 °C) colaba, porque esos valores recorrían
 * media rampa. La 1.2.2 cambió —con razón— el número que representa a un equipo:
 * ahora es el AIRE DE ENTRADA, que en una sala sana va de 18 a 32 °C. Ese rango
 * entero cae en el primer 18 % de la rampa vieja, así que todo el mapa térmico
 * salía del mismo color: el canal rojo no llegaba a moverse ni dos unidades
 * entre el rack más frío y el más caliente. Un mapa de calor que no podía
 * enseñar calor.
 *
 * Ahora hay dos rampas, y cada una está anclada a los umbrales REALES que usa el
 * backend para decidir el estado (backend/app/services/collector.py):
 *
 *   entrada     ASHRAE   aviso 27 °C   crítico 32 °C
 *   componente  CPU/disco aviso 70 °C   crítico 80 °C
 *
 * Así el ámbar del mapa aparece exactamente cuando el equipo pasa a "warning" y
 * el rojo cuando pasa a "critical", que es lo que ya dice la barra de "Estado
 * del parque" justo al lado. Si alguien cambia los umbrales del backend, hay que
 * mover estas paradas con ellos.
 */
export type EscalaTermica = "entrada" | "componente";

/** Los mismos nombres que el backend trata como aire de entrada
    (services/collector.py: METRICAS_DE_ENTRADA). Si las dos listas se separan,
    el color deja de coincidir con el estado. */
export const METRICAS_DE_ENTRADA = [
  "temp_inlet",
  "temp_ambient",
  "temp_intake",
  "temp_room",
] as const;

/** Qué escala le toca a una métrica. Sin nombre se asume entrada, que es lo que
    representa a un dispositivo en el panel desde la 1.2.2. */
export function escalaDe(metricName?: string | null): EscalaTermica {
  if (!metricName) return "entrada";
  return (METRICAS_DE_ENTRADA as readonly string[]).includes(metricName)
    ? "entrada"
    : "componente";
}

/** Los umbrales de cada escala, para la leyenda y para las pruebas. */
export const UMBRALES: Record<EscalaTermica, { frio: number; aviso: number; critico: number; tope: number }> = {
  entrada: { frio: 15, aviso: 27, critico: 32, tope: 38 },
  componente: { frio: 25, aviso: 70, critico: 80, tope: 95 },
};

type Parada = { t: number; c: [number, number, number] };

// Rampa de FONDO (celdas del rack, barras). Colores vivos.
const STOPS: Record<EscalaTermica, Parada[]> = {
  // La parada repetida (21 y 25, 45 y 65) mantiene el verde plano en toda la
  // zona sana. Sin ella el degradado sale de verde en cuanto pasa la parada
  // anterior y un equipo a 25 °C —normal— ya se veía amarillento: el color
  // avisaba antes que el producto.
  entrada: [
    { t: 15, c: [56, 189, 248] }, // #38BDF8 frío
    { t: 21, c: [52, 211, 153] }, // #34D399 nominal
    { t: 25, c: [52, 211, 153] }, // el verde aguanta hasta aquí
    { t: 27, c: [251, 191, 36] }, // #FBBF24 aviso    <- umbral real
    { t: 32, c: [248, 113, 113] }, // #F87171 crítico <- umbral real
    { t: 38, c: [220, 38, 38] }, // #DC2626 muy por encima
  ],
  componente: [
    { t: 25, c: [56, 189, 248] },
    { t: 45, c: [52, 211, 153] },
    { t: 65, c: [52, 211, 153] },
    { t: 70, c: [251, 191, 36] }, // <- umbral real
    { t: 80, c: [248, 113, 113] }, // <- umbral real
    { t: 95, c: [220, 38, 38] },
  ],
};

// Rampa de TEXTO para el tema claro: los mismos cortes, oscurecidos para que el
// número siga leyéndose sobre blanco (WCAG AA). En oscuro vale la de arriba.
const STOPS_INK: Record<EscalaTermica, Parada[]> = {
  entrada: [
    { t: 15, c: [3, 105, 161] }, // #0369A1 azul frío
    { t: 21, c: [4, 120, 87] }, // #047857 verde nominal
    { t: 25, c: [4, 120, 87] }, // el verde aguanta hasta aquí
    { t: 27, c: [180, 83, 9] }, // #B45309 ámbar aviso
    { t: 32, c: [185, 28, 28] }, // #B91C1C rojo crítico
    { t: 38, c: [153, 27, 27] }, // #991B1B
  ],
  componente: [
    { t: 25, c: [3, 105, 161] },
    { t: 45, c: [4, 120, 87] },
    { t: 65, c: [4, 120, 87] },
    { t: 70, c: [180, 83, 9] },
    { t: 80, c: [185, 28, 28] },
    { t: 95, c: [153, 27, 27] },
  ],
};

function lerp(a: number, b: number, f: number): number {
  return Math.round(a + (b - a) * f);
}

function rgb(c: [number, number, number]): string {
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

function recorrer(temp: number, S: Parada[]): string {
  if (temp <= S[0].t) return rgb(S[0].c);
  if (temp >= S[S.length - 1].t) return rgb(S[S.length - 1].c);
  for (let i = 0; i < S.length - 1; i++) {
    const lo = S[i];
    const hi = S[i + 1];
    if (temp >= lo.t && temp <= hi.t) {
      const f = (temp - lo.t) / (hi.t - lo.t);
      return rgb([
        lerp(lo.c[0], hi.c[0], f),
        lerp(lo.c[1], hi.c[1], f),
        lerp(lo.c[2], hi.c[2], f),
      ]);
    }
  }
  return rgb(S[S.length - 1].c);
}

/** El degradado CSS de una escala, generado a partir de las MISMAS paradas que
    pinta el mapa. La leyenda llevaba sus colores escritos a mano y sus extremos
    ("15°" y "90°") ya no tenían nada que ver con lo que se veía debajo: quien la
    mirara se llevaba una idea equivocada de qué significaba cada color. */
export function gradienteCss(escala: EscalaTermica = "entrada"): string {
  const S = STOPS[escala];
  const min = S[0].t;
  const span = S[S.length - 1].t - min || 1;
  const tramos = S.map((p) => `${rgb(p.c)} ${(((p.t - min) / span) * 100).toFixed(1)}%`);
  return `linear-gradient(90deg, ${tramos.join(", ")})`;
}

/** Dónde cae un umbral dentro de la barra de la leyenda, en % de izquierda. */
export function posicionEnLeyenda(temp: number, escala: EscalaTermica = "entrada"): number {
  const S = STOPS[escala];
  const min = S[0].t;
  const span = S[S.length - 1].t - min || 1;
  return Math.max(0, Math.min(100, ((temp - min) / span) * 100));
}

/** RGB de una temperatura en la escala que le corresponda. */
export function thermalColor(
  temp: number | null | undefined,
  escala: EscalaTermica = "entrada",
): string {
  if (temp === null || temp === undefined || Number.isNaN(temp)) {
    return "#3a4553"; // gris apagado para "sin datos"
  }
  return recorrer(temp, STOPS[escala]);
}

/** Color seguro para TEXTO según el tema. El claro usa la rampa oscurecida
    (sigue siendo frío=azul, caliente=rojo) para no perder contraste. */
export function thermalTextColor(
  temp: number | null | undefined,
  light: boolean,
  escala: EscalaTermica = "entrada",
): string {
  if (!light) return thermalColor(temp, escala);
  if (temp === null || temp === undefined || Number.isNaN(temp)) return "#475569";
  return recorrer(temp, STOPS_INK[escala]);
}

export const STATUS_COLOR: Record<DeviceStatusKind, string> = {
  ok: "#34D399",
  warning: "#FBBF24",
  critical: "#F87171",
  nodata: "#5b6774",
  maintenance: "#38BDF8",
};

/** Etiquetas en inglés, solo como último recurso. La interfaz usa t("statusOk")
    y compañía: estas estaban escritas a mano en inglés y salían sin traducir en
    medio de un panel en español. */
export const STATUS_LABEL: Record<DeviceStatusKind, string> = {
  ok: "Nominal",
  warning: "Warning",
  critical: "Critical",
  nodata: "No data",
  maintenance: "Maintenance",
};

/** La clave de traducción de cada estado. */
export const STATUS_I18N_KEY: Record<DeviceStatusKind, string> = {
  ok: "statusOk",
  warning: "statusWarning",
  critical: "statusCritical",
  nodata: "statusNodata",
  maintenance: "statusMaintenance",
};

export const SEVERITY_COLOR: Record<Severity, string> = {
  info: "#38BDF8",
  warning: "#FBBF24",
  critical: "#F87171",
};

/** Human-friendly relative time, e.g. "3m ago". */
export function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function formatTemp(t: number | null | undefined): string {
  if (t === null || t === undefined || Number.isNaN(t)) return "—";
  return `${t.toFixed(1)}°`;
}

/** Temperature with an explicit unit, for headline KPIs where the bare degree
    symbol is ambiguous (device tiles already show °C — keep it consistent). */
export function formatTempC(t: number | null | undefined): string {
  if (t === null || t === undefined || Number.isNaN(t)) return "—";
  return `${t.toFixed(1)}°C`;
}

/** El valor de una alerta, con la unidad que de verdad le corresponde.
 *
 *  La lista de alertas pintaba SIEMPRE `formatTemp(a.value)`, es decir, un
 *  símbolo de grados pegado a cualquier número. Un ventilador parado salía como
 *  «450.0°», una CPU al 85 % como «85.0°» y una trampa SNMP como «0.0°». En un
 *  producto cuya credibilidad entera descansa sobre números de temperatura, un
 *  grado centígrado donde no lo hay no es un detalle de estilo: es un dato
 *  falso, y en la pantalla donde más se mira. */
export function formatAlertValue(metric: string | null | undefined, v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const m = (metric || "").toLowerCase();
  if (m === "device_reachable") return v >= 1 ? "responde" : "sin respuesta";
  if (m === "snmp_trap") return v > 1 ? `×${Math.round(v)}` : "";
  if (m.startsWith("temp")) return formatTemp(v);
  if (m.includes("rpm") || m.includes("fan")) return `${Math.round(v)} rpm`;
  if (m.includes("load") || m.includes("used") || m.includes("pct") || m.includes("percent"))
    return `${v.toFixed(0)}%`;
  if (m.includes("volt")) return `${v.toFixed(1)} V`;
  if (m.includes("watt") || m.includes("power")) return `${v.toFixed(0)} W`;
  if (m.includes("humid")) return `${v.toFixed(0)}% RH`;
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
