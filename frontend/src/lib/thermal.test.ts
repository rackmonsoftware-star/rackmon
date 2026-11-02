import { describe, expect, it } from "vitest";

import {
  METRICAS_DE_ENTRADA,
  SEVERITY_COLOR,
  STATUS_COLOR,
  STATUS_I18N_KEY,
  STATUS_LABEL,
  UMBRALES,
  escalaDe,
  formatAlertValue,
  formatTemp,
  gradienteCss,
  posicionEnLeyenda,
  thermalColor,
  thermalTextColor,
  timeAgo,
} from "./thermal";

function rgbA(s: string): [number, number, number] {
  const m = s.match(/^rgb\((\d+), (\d+), (\d+)\)$/);
  if (!m) throw new Error(`no es un rgb(): ${s}`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

/** Distancia euclídea entre dos colores, 0..441. */
function distancia(a: string, b: string): number {
  const [r1, g1, b1] = rgbA(a);
  const [r2, g2, b2] = rgbA(b);
  return Math.hypot(r1 - r2, g1 - g2, b1 - b2);
}

// Se mira la RELACION entre canales, no valores absolutos: la rampa del tema
// claro es la misma pero oscurecida, y un umbral fijo la daba por "no fría"
// cuando lo era.
const esCalido = (s: string) => {
  const [r, g, b] = rgbA(s);
  return r > g && r > b; // el rojo manda: ámbar o rojo
};
const esRojo = (s: string) => {
  const [r, g, b] = rgbA(s);
  return r > g * 1.5 && r > b * 1.5; // rojo de verdad, no ámbar
};
const esFrio = (s: string) => {
  const [r, g, b] = rgbA(s);
  return r < g && r < b; // el rojo es el canal más bajo: cian o verde
};
/** Cuánto tira al rojo, de -255 (frío del todo) a 255. */
const calidez = (s: string) => {
  const [r, g, b] = rgbA(s);
  return r - Math.max(g, b);
};

describe("thermalColor: valores ausentes", () => {
  it("devuelve gris cuando no hay dato", () => {
    expect(thermalColor(null)).toBe("#3a4553");
    expect(thermalColor(undefined)).toBe("#3a4553");
    expect(thermalColor(NaN)).toBe("#3a4553");
  });
});

// El fallo real que motivó estas pruebas: el panel pasó a enseñar temperatura de
// ENTRADA (18-32 °C) y la rampa seguía anclada de 15 a 90 °C, pensada para CPU.
// Resultado: los 119 huecos del mapa salían del mismo color —el canal rojo no se
// movía ni dos unidades entre el rack más frío y el más caliente— y un equipo a
// 32 °C, crítico según el propio producto, se pintaba verde.
describe("escala de ENTRADA: el color dice lo mismo que el estado", () => {
  const { aviso, critico } = UMBRALES.entrada;

  it("por debajo del aviso se ve frío, nunca cálido", () => {
    for (const t of [16, 18, 20, 22, 24, 25]) {
      expect(esFrio(thermalColor(t)), `${t} °C debería verse frío`).toBe(true);
      expect(esCalido(thermalColor(t)), `${t} °C no debería verse cálido`).toBe(false);
    }
  });

  it("en el umbral de aviso (27 °C) ya se ve cálido", () => {
    expect(esCalido(thermalColor(aviso))).toBe(true);
    expect(esCalido(thermalColor(aviso + 2))).toBe(true);
  });

  it("en el umbral crítico (32 °C) se ve ROJO, no verde", () => {
    const c = thermalColor(critico);
    expect(esRojo(c), `32 °C salió ${c}`).toBe(true);
    expect(esFrio(c)).toBe(false);
  });

  it("el rango real de una sala recorre la rampa de verdad", () => {
    // Antes esta distancia era 65 sobre 441: un mapa de calor que no podía
    // enseñar calor. Si alguien vuelve a anclar la rampa a un rango de CPU,
    // esta prueba cae.
    expect(distancia(thermalColor(18), thermalColor(32))).toBeGreaterThan(180);
  });

  it("el canal rojo sube de verdad entre frío y crítico", () => {
    const frio = rgbA(thermalColor(18))[0];
    const caliente = rgbA(thermalColor(32))[0];
    expect(caliente - frio).toBeGreaterThan(150); // antes: -2
  });

  it("toda la zona sana se ve fría, de punta a punta", () => {
    // De 15 a 21 el color gira de cian a verde: cambia de tono pero no se
    // calienta. Lo que importa aquí no es que suba, es que NADA por debajo del
    // aviso parezca caliente.
    for (let t = 15; t <= 25; t += 0.5) {
      expect(esFrio(thermalColor(t)), `${t} °C no se ve frío`).toBe(true);
    }
  });

  it("es monótona desde la zona sana hacia arriba", () => {
    // No vale mirar solo el canal rojo: el rojo oscuro del extremo (220) tiene
    // MENOS rojo que el salmón del umbral crítico (248). Lo que tiene que crecer
    // es cuánto tira al rojo frente al resto de canales.
    let anterior = -Infinity;
    for (let t = 21; t <= 38; t += 0.5) {
      const c = calidez(thermalColor(t));
      expect(c, `se enfría al pasar por ${t} °C`).toBeGreaterThanOrEqual(anterior - 1);
      anterior = Math.max(anterior, c);
    }
  });

  it("se queda quieta fuera de los extremos", () => {
    expect(thermalColor(5)).toBe(thermalColor(15));
    expect(thermalColor(200)).toBe(thermalColor(38));
  });
});

describe("escala de COMPONENTE: una CPU a 32 °C está en reposo", () => {
  const { aviso, critico } = UMBRALES.componente;

  it("32 °C de CPU se ve frío, no crítico", () => {
    expect(esFrio(thermalColor(32, "componente"))).toBe(true);
  });

  it("avisa a 70 y es rojo a 80", () => {
    expect(esCalido(thermalColor(aviso, "componente"))).toBe(true);
    expect(esRojo(thermalColor(critico, "componente"))).toBe(true);
  });

  it("la misma temperatura se pinta distinta en cada escala", () => {
    // Esto es lo que hacía falta separar: 70 °C es aviso para una CPU y un
    // horno para el aire de entrada.
    expect(thermalColor(70, "entrada")).not.toBe(thermalColor(70, "componente"));
  });
});

describe("thermalTextColor", () => {
  it("en oscuro usa la misma rampa que el fondo", () => {
    expect(thermalTextColor(30, false)).toBe(thermalColor(30));
  });

  it("en claro respeta los mismos umbrales", () => {
    expect(esFrio(thermalTextColor(22, true))).toBe(true);
    expect(esCalido(thermalTextColor(28, true))).toBe(true);
    // El fallo tal cual se vio en la demo: 32,9 °C pintado en verde.
    const c = thermalTextColor(32.9, true);
    expect(esFrio(c), `32,9 °C en claro salió ${c}`).toBe(false);
  });

  it("en claro los números se leen sobre blanco", () => {
    // Luminancia relativa baja = contraste suficiente sobre fondo claro.
    for (const t of [18, 24, 27, 30, 33]) {
      const [r, g, b] = rgbA(thermalTextColor(t, true));
      const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
      expect(lum, `${t} °C demasiado claro para leerse`).toBeLessThan(0.5);
    }
  });

  it("devuelve gris cuando no hay dato", () => {
    expect(thermalTextColor(null, true)).toBe("#475569");
    expect(thermalTextColor(undefined, false)).toBe("#3a4553");
  });
});

describe("escalaDe", () => {
  it("reconoce las métricas de aire de entrada", () => {
    for (const m of METRICAS_DE_ENTRADA) {
      expect(escalaDe(m)).toBe("entrada");
    }
  });

  it("todo lo demás es componente", () => {
    expect(escalaDe("temp_cpu")).toBe("componente");
    expect(escalaDe("temp_exhaust")).toBe("componente");
    expect(escalaDe("temp_disk")).toBe("componente");
  });

  it("sin nombre asume entrada, que es lo que representa a un equipo", () => {
    expect(escalaDe(undefined)).toBe("entrada");
    expect(escalaDe(null)).toBe("entrada");
    expect(escalaDe("")).toBe("entrada");
  });

  it("la lista es la misma que la del backend", () => {
    // backend/app/services/collector.py: METRICAS_DE_ENTRADA. Si las dos se
    // separan, el color deja de coincidir con el estado y nadie se entera.
    expect([...METRICAS_DE_ENTRADA].sort()).toEqual(
      ["temp_ambient", "temp_inlet", "temp_intake", "temp_room"].sort(),
    );
  });
});

describe("leyenda", () => {
  it("el degradado sale de las mismas paradas que el mapa", () => {
    const g = gradienteCss("entrada");
    expect(g.startsWith("linear-gradient(90deg,")).toBe(true);
    // Los colores de los extremos tienen que ser los de la rampa.
    expect(g).toContain(thermalColor(UMBRALES.entrada.frio));
    expect(g).toContain(thermalColor(UMBRALES.entrada.tope));
  });

  it("las marcas de umbral caen dentro de la barra y en orden", () => {
    const a = posicionEnLeyenda(UMBRALES.entrada.aviso);
    const c = posicionEnLeyenda(UMBRALES.entrada.critico);
    expect(a).toBeGreaterThan(0);
    expect(c).toBeLessThan(100);
    expect(a).toBeLessThan(c);
  });
});

describe("timeAgo", () => {
  it("handles null", () => {
    expect(timeAgo(null)).toBe("—");
  });
  it("formats minutes and hours", () => {
    expect(timeAgo(new Date(Date.now() - 125_000).toISOString())).toBe("2m ago");
    expect(timeAgo(new Date(Date.now() - 2 * 3600_000).toISOString())).toBe("2h ago");
    expect(timeAgo(new Date().toISOString())).toMatch(/ago$/);
  });
});

describe("formatTemp", () => {
  it("formats and guards", () => {
    expect(formatTemp(null)).toBe("—");
    expect(formatTemp(69.94)).toBe("69.9°");
    expect(formatTemp(40)).toBe("40.0°");
  });
});

describe("colour tables", () => {
  it("cover every status and severity", () => {
    for (const k of ["ok", "warning", "critical", "nodata", "maintenance"] as const) {
      expect(STATUS_COLOR[k]).toMatch(/^#/);
      expect(STATUS_LABEL[k]).toBeTruthy();
      expect(STATUS_I18N_KEY[k]).toBeTruthy();
    }
    for (const s of ["info", "warning", "critical"] as const) {
      expect(SEVERITY_COLOR[s]).toMatch(/^#/);
    }
  });
});

describe("formatAlertValue — el grado que no era", () => {
  // La lista de alertas pegaba un símbolo de grados a CUALQUIER valor. En un
  // producto que se vende por medir temperaturas, un "450.0°" junto a un
  // ventilador parado es un dato falso en la pantalla que más se mira.
  it("un ventilador parado no está a 450 grados", () => {
    expect(formatAlertValue("fan_rpm", 450)).toBe("450 rpm");
  });

  it("una CPU al 85 % no está a 85 grados", () => {
    expect(formatAlertValue("cpu_load", 85)).toBe("85%");
  });

  it("un equipo que no contesta no está a 0 grados", () => {
    expect(formatAlertValue("device_reachable", 0)).toBe("sin respuesta");
    expect(formatAlertValue("device_reachable", 1)).toBe("responde");
  });

  it("una trampa SNMP repetida cuenta veces, no grados", () => {
    expect(formatAlertValue("snmp_trap", 50)).toBe("×50");
    expect(formatAlertValue("snmp_trap", 1)).toBe("");
  });

  it("una temperatura sigue siendo una temperatura", () => {
    expect(formatAlertValue("temp_inlet", 32.4)).toBe("32.4°");
    expect(formatAlertValue("temp_cpu", 81)).toBe("81.0°");
    expect(formatAlertValue("temp_inlet_2", 28.05)).toBe("28.1°");
  });

  it("sin valor, una raya", () => {
    expect(formatAlertValue("temp_inlet", null)).toBe("—");
    expect(formatAlertValue("temp_inlet", undefined)).toBe("—");
    expect(formatAlertValue("fan_rpm", NaN)).toBe("—");
  });
});
