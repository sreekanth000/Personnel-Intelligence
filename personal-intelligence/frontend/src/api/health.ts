/**
 * Typed API client for /health endpoint.
 */

import { request } from "./client";
import type { HealthCheckResponse } from "../types";

export const healthApi = {
  checkHealth: (): Promise<HealthCheckResponse> =>
    request<HealthCheckResponse>("/health"),
};
