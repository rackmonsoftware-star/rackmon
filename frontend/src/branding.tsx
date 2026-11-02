import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { api } from "./api";

export interface Branding {
  product_name: string;
  accent: string;
  logo_url: string | null;
}

const DEFAULT: Branding = { product_name: "RackMon", accent: "#22D3EE", logo_url: null };

const Ctx = createContext<Branding>(DEFAULT);

/** "#22D3EE" / "#2DE" -> "34 211 238" (space-separated RGB channels for the CSS var). */
function hexToRgbChannels(hex: string): string | null {
  let h = hex.trim().replace(/^#/, "");
  if (/^[0-9a-fA-F]{3}$/.test(h)) h = h.split("").map((c) => c + c).join(""); // #abc -> #aabbcc
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  const n = parseInt(h, 16);
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

export function BrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<Branding>(DEFAULT);

  useEffect(() => {
    api
      .branding()
      .then((b) => {
        setBranding(b);
        const rgb = hexToRgbChannels(b.accent);
        if (rgb) {
          document.documentElement.style.setProperty("--accent-rgb", rgb);
          // Choose a readable ink for text/icons drawn ON the accent based on its
          // luminance, so a dark white-label accent doesn't render invisible text.
          const [r, g, bl] = rgb.split(" ").map(Number);
          const lum = (0.299 * r + 0.587 * g + 0.114 * bl) / 255;
          document.documentElement.style.setProperty("--accent-ink", lum > 0.6 ? "#04222a" : "#ffffff");
        }
        if (b.product_name) document.title = `${b.product_name} — Thermal Monitoring`;
      })
      .catch(() => undefined);
  }, []);

  return <Ctx.Provider value={branding}>{children}</Ctx.Provider>;
}

export function useBranding(): Branding {
  return useContext(Ctx);
}
