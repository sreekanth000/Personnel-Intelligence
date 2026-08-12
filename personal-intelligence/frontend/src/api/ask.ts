/**
 * Typed API client for GPT-4.1 Reasoning Layer (/api/v1/ask).
 */

import { request } from "./client";
import type { AskRequest, AskResponse } from "../types";

export const askApi = {
  askQuestion: (data: AskRequest): Promise<AskResponse> =>
    request<AskResponse>("/api/v1/ask", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};
