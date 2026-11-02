import { useCallback, useEffect, useRef, useState } from "react";

import { accessToken } from "./api";

/** Fetch on mount and re-fetch on an interval. Returns data, error, loading, refetch. */
export function usePoll<T>(
  fetcher: () => Promise<T>,
  intervalMs = 10000,
  deps: unknown[] = [],
): { data: T | null; error: string | null; loading: boolean; refetch: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setLoading(true);
    run();
    if (intervalMs <= 0) return;
    const id = window.setInterval(run, intervalMs);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps]);

  return { data, error, loading, refetch: run };
}

export type WsStatus = "connecting" | "connected" | "disconnected";

interface WsMessage {
  type: string;
  [key: string]: unknown;
}

/**
 * Subscribe to the realtime stream for the given topics. Calls onMessage for
 * each frame. Reconnects automatically with capped backoff.
 */
export function useWebSocket(
  topics: string[],
  onMessage: (msg: WsMessage) => void,
): WsStatus {
  const [status, setStatus] = useState<WsStatus>("connecting");
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const topicsKey = topics.join(",");

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    let timer: number | undefined;

    const connect = () => {
      const token = accessToken();
      if (!token) {
        setStatus("disconnected");
        return;
      }
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const url = `${proto}://${window.location.host}/api/v1/stream?token=${encodeURIComponent(
        token,
      )}&topics=${encodeURIComponent(topicsKey)}`;
      setStatus("connecting");
      ws = new WebSocket(url);

      ws.onopen = () => {
        retry = 0;
        setStatus("connected");
      };
      ws.onmessage = (ev) => {
        try {
          onMessageRef.current(JSON.parse(ev.data) as WsMessage);
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        setStatus("disconnected");
        if (closed) return;
        retry = Math.min(retry + 1, 6);
        const delay = Math.min(1000 * 2 ** retry, 15000);
        timer = window.setTimeout(connect, delay);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      ws?.close();
    };
  }, [topicsKey]);

  return status;
}
