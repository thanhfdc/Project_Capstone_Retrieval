export interface EntityRef {
  entity_id: string;
  name: string;
  entity_type: string;
}

export interface Item {
  image_id: string;
  thumb_url: string;
  width: number;
  height: number;
  entities: { id: string; name: string }[];
  description: string;
  source_url: string | null;
  image_url: string | null;
}

export interface Group {
  intent_id: string;
  label: string;
  status: string;
  image_ids: string[];
  explanation: string[];
  retrieval?: string[];
}

export interface SearchResponse {
  request_id: string;
  status: string;
  query_type: "single" | "multi_intent" | "multi_hop";
  interpretation: {
    parser: string;
    combine: string;
    location: EntityRef | null;
    location_text: string;
    intents: {
      label: string;
      seeds: EntityRef[];
      entity_operator: string;
      relations: string[];
      visual_text: string;
      fuzzy: boolean;
    }[];
  };
  groups: Group[];
  items: Record<string, Item>;
  clarification_options: { mention: string; candidates: EntityRef[] }[];
  warnings: string[];
  metrics: Record<string, number | boolean>;
}

export interface Stats {
  serving_images: number;
  encoder_online: string;
}

export async function search(
  query: string,
  selected: string[],
  signal: AbortSignal,
): Promise<SearchResponse> {
  const res = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: 24, selected_entity_ids: selected }),
    signal,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function stats(): Promise<Stats | null> {
  try {
    const res = await fetch("/api/corpus/stats");
    return res.ok ? res.json() : null;
  } catch {
    return null;
  }
}
