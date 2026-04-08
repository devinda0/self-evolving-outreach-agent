import { create } from "zustand";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UIAction {
  id: string;
  label: string;
  action_type: string;
  payload: Record<string, unknown>;
}

export interface UIFrame {
  type: "ui_component" | "text" | "progress" | "error";
  component?: string;
  instance_id: string;
  props: Record<string, unknown>;
  actions: UIAction[];
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  uiComponent?: UIFrame;
  timestamp: Date;
}

export type WsStatus = "connecting" | "connected" | "disconnected";

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

interface CampaignStore {
  sessionId: string | null;
  messages: Message[];
  isStreaming: boolean;
  isPendingAction: boolean;
  currentStage: string | null;
  wsStatus: WsStatus;

  setSessionId: (id: string) => void;
  addUserMessage: (content: string) => void;
  appendToken: (token: string) => void;
  addUIFrame: (frame: UIFrame) => void;
  setStreaming: (val: boolean) => void;
  setPendingAction: (val: boolean) => void;
  setWsStatus: (status: WsStatus) => void;
  setCurrentStage: (stage: string | null) => void;
  addErrorMessage: (message: string) => void;
}

let nextMsgId = 0;
function genMsgId(): string {
  nextMsgId += 1;
  return `msg-${nextMsgId}`;
}

export const useCampaignStore = create<CampaignStore>((set) => ({
  sessionId: null,
  messages: [],
  isStreaming: false,
  isPendingAction: false,
  currentStage: null,
  wsStatus: "disconnected",

  setSessionId: (id) => set({ sessionId: id }),

  addUserMessage: (content) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: genMsgId(), role: "user", content, timestamp: new Date() },
      ],
    })),

  appendToken: (token) =>
    set((s) => {
      const msgs = [...s.messages];
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant" && !last.uiComponent) {
        msgs[msgs.length - 1] = { ...last, content: last.content + token };
      } else {
        msgs.push({
          id: genMsgId(),
          role: "assistant",
          content: token,
          timestamp: new Date(),
        });
      }
      return { messages: msgs };
    }),

  addUIFrame: (frame) =>
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id: genMsgId(),
          role: "assistant",
          content: "",
          uiComponent: frame,
          timestamp: new Date(),
        },
      ],
    })),

  setStreaming: (val) => set({ isStreaming: val }),
  setPendingAction: (val) => set({ isPendingAction: val }),
  setWsStatus: (status) => set({ wsStatus: status }),
  setCurrentStage: (stage) => set({ currentStage: stage }),

  addErrorMessage: (message) =>
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id: genMsgId(),
          role: "assistant",
          content: `Error: ${message}`,
          timestamp: new Date(),
        },
      ],
    })),
}));
