import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getToken } from "./auth";

export interface BotEvent {
  type: string;
  ts?: number;
  [k: string]: unknown;
}

/** Subscribe to the live event stream; keep the last `max` events and
 *  invalidate affected React Query caches as events arrive. */
export function useEventStream(max = 25): BotEvent[] {
  const [events, setEvents] = useState<BotEvent[]>([]);
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/dashboard/ws?token=${token}`);
      wsRef.current = ws;
      ws.onmessage = (m) => {
        try {
          const ev = JSON.parse(m.data) as BotEvent;
          setEvents((prev) => [{ ...ev, ts: ev.ts ?? Date.now() / 1000 }, ...prev].slice(0, max));
          if (
            ev.type.startsWith("payment") ||
            ev.type.startsWith("admin") ||
            ev.type === "user:registered"
          ) {
            qc.invalidateQueries({ queryKey: ["stats"] });
          }
          if (ev.type.startsWith("broadcast")) {
            qc.invalidateQueries({ queryKey: ["broadcasts"] });
          }
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        if (!closed) retry = setTimeout(connect, 4000);
      };
    };
    connect();

    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      wsRef.current?.close();
    };
  }, [qc, max]);

  return events;
}
