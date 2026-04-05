import { create } from "zustand";

interface CampaignState {
  sessionId: string | null;
  setSessionId: (id: string) => void;
}

export const useCampaignStore = create<CampaignState>((set) => ({
  sessionId: null,
  setSessionId: (id) => set({ sessionId: id }),
}));
