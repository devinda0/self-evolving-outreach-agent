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
          store.setWaitingForResponse(false);
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

  useEffect(() => {
    if (!sessionId) return;

    let isActive = true;

    const connect = () => {
      if (!isActive) return;

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
        const store = useCampaignStore.getState();
        const hadPendingWork = store.isPendingAction || store.isWaitingForResponse;
        store.setWsStatus("disconnected");
        store.setStreaming(false);
        store.setPendingAction(false);
        store.setWaitingForResponse(false);
        if (hadPendingWork) {
          store.addErrorMessage("Connection lost while processing the request. Please retry.");
        }
        if (!isActive) return;
        reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      isActive = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [sessionId, dispatch]);

  const sendMessage = useCallback((text: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      const store = useCampaignStore.getState();
      store.setPendingAction(false);
      store.setWaitingForResponse(false);
      store.addErrorMessage("Connection is not ready. Please retry in a moment.");
      return;
    }
    wsRef.current?.send(JSON.stringify({ type: "user_message", content: text }));
  }, []);

  const sendUIAction = useCallback(
    (instanceId: string, actionId: string, payload: Record<string, unknown> = {}) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        const store = useCampaignStore.getState();
        store.setPendingAction(false);
        store.setWaitingForResponse(false);
        store.addErrorMessage("Connection is not ready. Please retry in a moment.");
        return;
      }
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
