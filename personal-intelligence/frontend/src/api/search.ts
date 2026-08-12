import { request } from "./client";

export interface UISearchResult {
  id: string;
  result_type: string;
  subtype?: string;
  title: string;
  current_status?: string;
  timestamp?: string;
  confidence?: number;
  evidence_count?: number;
  snippet?: string;
}

export const searchApi = {
  globalSearch: (query: string): Promise<UISearchResult[]> =>
    request<UISearchResult[]>(
      `/api/v1/ui/search?q=${encodeURIComponent(query)}`,
    ),
};
