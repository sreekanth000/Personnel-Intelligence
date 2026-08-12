import { request } from "./client";

export interface MyWorldNode {
  id: string;
  label: string;
  category: string;
  epistemic_state: string;
  confidence: number;
}

export interface MyWorldEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  epistemic_state: string;
  confidence: number;
}

export interface MyWorldDTO {
  nodes: MyWorldNode[];
  edges: MyWorldEdge[];
}

export const myWorldApi = {
  getCanvas: (): Promise<MyWorldDTO> =>
    request<MyWorldDTO>("/api/v1/ui/my-world"),
};
