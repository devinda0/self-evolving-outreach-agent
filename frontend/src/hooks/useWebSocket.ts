import { useEffect, useRef, useCallback } from "react";

const WS_URL = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000";

export function useWebSocket(path: string, onMessage: (data: unknown) => void) {
  const wsRef = useRef<WebSocket | null>(null);

  const send = useCallback((data: unknown) => {
    wsRef.current?.send(JSON.stringify(data));
  }, []);

  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}${path}`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      onMessage(JSON.parse(event.data as string));
    };

    return () => {
      ws.close();
    };
  }, [path, onMessage]);

  return { send };
}
