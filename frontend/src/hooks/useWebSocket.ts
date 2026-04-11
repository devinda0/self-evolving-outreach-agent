import { useEffect, useRef, useCallback } from "react";
import { useCampaignStore } from "../store/campaignStore";

const WS_URL = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000";
const RECONNECT_DELAY_MS = 3_000;

interface WsFrame {
  type: string;
  [key: string]: unknown;
}

export function useWebSocket(sessionId: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const dispatch = useCallback(
    (frame: WsFrame) => {
      const store = useCampaignStore.getState();
      switch (frame.type) {
        case "token":
          store.appendToken(frame.content as string);
          store.setStreaming(true);
          store.setPendingAction(false);
          break;
        case "token_end":
          store.setStreaming(false);
          store.setPendingAction(false);
          break;
        case "ui_component":
          store.addUIFrame(frame as unknown as Parameters<typeof store.addUIFrame>[0]);
          store.setPendingAction(false);
          break;
        case "text": {
          // Text frames from answer_node / update_context_node carry the
          // LLM response in props.content — render as a regular assistant message.
          const props = (frame as Record<string, unknown>).props as Record<string, unknown> | undefined;
          const content = props?.content;
          if (typeof content === "string" && content) {
            store.appendToken(content);
          }
          store.setPendingAction(false);
          break;
        }
        case "progress":
          store.setCurrentStage((frame.stage as string) ?? null);
          store.setPendingAction(false);
          break;
        case "error":
          store.addErrorMessage((frame.message as string) ?? "Unknown error");
          store.setPendingAction(false);
          break;
        default:
          break;
      }
    },
    [],
  );

  const connect = useCallback(() => {
    if (!sessionId) return;

    useCampaignStore.getState().setWsStatus("connecting");
    const ws = new WebSocket(`${WS_URL}/ws/campaign/${sessionId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      useCampaignStore.getState().setWsStatus("connected");
    };

    ws.onmessage = (event) => {
      try {
        const frame: WsFrame = JSON.parse(event.data as string);
        dispatch(frame);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      useCampaignStore.getState().setWsStatus("disconnected");
      useCampaignStore.getState().setStreaming(false);
      // Auto-reconnect
      reconnectTimer.current = setTimeout(() => {
        connect();
      }, RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [sessionId, dispatch]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const sendMessage = useCallback((text: string) => {
    wsRef.current?.send(JSON.stringify({ type: "user_message", content: text }));
  }, []);

  const sendUIAction = useCallback(
    (instanceId: string, actionId: string, payload: Record<string, unknown> = {}) => {
      wsRef.current?.send(
        JSON.stringify({
          type: "ui_action",
          instance_id: instanceId,
          action_id: actionId,
          payload,
        }),
      );
    },
    [],
  );

  return { sendMessage, sendUIAction };
}
