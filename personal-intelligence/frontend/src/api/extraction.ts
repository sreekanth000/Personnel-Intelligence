import { request } from "./client";

export interface ExtractionMetrics {
  emails_processed: number;
  entities_extracted: number;
  relationships_extracted: number;
  claims_extracted: number;
  events_extracted: number;
  extraction_failures: number;
  low_confidence_extractions: number;
  unresolved_entities: number;
  unresolved_relationships: number;
  conflicting_relationships: number;
  pending_confirmations: number;
}

export interface ExtractionSample {
  id: string;
  email_snippet: string;
  extraction_subject: string;
  extraction_predicate: string;
  extraction_object: string;
  confidence: number;
  final_wm_status: string;
  review_status: string;
}

export const extractionApi = {
  getMetrics: (): Promise<ExtractionMetrics> =>
    request<ExtractionMetrics>("/api/v1/extraction/metrics"),

  getSamples: (): Promise<ExtractionSample[]> =>
    request<ExtractionSample[]>("/api/v1/extraction/samples"),
};
