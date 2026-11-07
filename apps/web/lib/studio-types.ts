import type { SpanIssue } from "./highlight";

export const PLATFORMS = [
  { id: "linkedin", label: "LinkedIn" },
  { id: "x", label: "X post" },
  { id: "x_thread", label: "X thread" },
  { id: "instagram_carousel", label: "Instagram carousel" },
  { id: "linkedin_carousel", label: "LinkedIn carousel (PDF)" },
  { id: "instagram_reel", label: "Instagram reel" },
  { id: "hashnode", label: "Hashnode article" },
] as const;
export type Platform = (typeof PLATFORMS)[number]["id"];
export const PLATFORM_LABEL: Record<string, string> = Object.fromEntries(PLATFORMS.map((p) => [p.id, p.label]));

export type NeedInput = { question: string; why?: string };

export type ContentIdea = {
  id: string;
  seed_type: string;
  seed_id: string | null;
  angle_type: string;
  thesis: string;
  credibility: string;
  needs_input: NeedInput[];
  platforms: string[];
  risk: "low" | "medium" | "high" | string;
  status: string;
};

export type Claim = { sentence: string; source_ids: string[] };

export type Grade = {
  scores: Record<string, { points: number; why?: string }>;
  total: number;
  ai_phrases: string[];
  top_edits: string[];
  verdict?: string;
};

export type FactResult = { sentence: string; verdict: "supported" | "partially" | "unsupported"; evidence_span?: string; fix_suggestion?: string };

export type FactCheck = {
  results: FactResult[];
  unknown_source_ids: string[];
  uncited_sentences: string[];
  unsupported: string[];
  partially: string[];
};

export type Checks = {
  originality?: { max_similarity_to_own?: number; flags: { type: string; message: string; severity?: string }[] };
  safety?: { flags: { type: string; text: string; severity: string; note?: string }[] };
  attribution?: string[];
};

export type Slide = { title: string; body?: string; code?: string | null; mermaid?: string | null; steps?: string[]; alt?: string; visual_hint?: string };
export type Beat = { t_start: number; t_end: number; voiceover: string; on_screen: string; shot: string };
export type ReelScript = { hook: Beat; beats: Beat[]; caption?: string; cover_text?: string; hashtags?: string[]; audio_mood?: string };
export type Article = {
  seo_title: string;
  subtitle?: string;
  tldr?: string;
  body_md: string;
  tags?: string[];
  references?: (string | { title?: string; url: string })[];
  cover_title?: string;
};

export type DraftVersion = {
  id: string;
  version: number;
  label: string;
  body: string;
  thread: string[] | null;
  first_comment: string;
  claims: Claim[];
  grade: Grade | null;
  factcheck: FactCheck | null;
  aitell: { issues: SpanIssue[]; counters?: Record<string, number>; passed?: boolean } | null;
  checks: Checks | null;
  slides?: { template?: string; items: Slide[] } | null;
  script?: (ReelScript & { article?: undefined }) | { article: Article } | null;
  author: "ai" | "human" | string;
  voice_version: number;
  prompt_version: string;
  model: string;
  created_at: string;
  gate: string[];
};

export type Draft = {
  id: string;
  platform: Platform | string;
  format: string;
  status: string;
  idea: ContentIdea | null;
  pending_questions: NeedInput[];
  scheduled_for: string | null;
  timeliness_deadline: string | null;
  post_within_24h: boolean;
  evergreen: boolean;
  series_id: string | null;
  parent_draft_id: string | null;
  override: { reason?: string; overridden?: string[]; at?: string } | null;
  current: DraftVersion | null;
  updated_at: string;
  versions?: DraftVersion[];
};

export type Asset = { id: string; kind: string; meta: Record<string, unknown>; url: string };

export type BoardCard = ({ kind: "idea" } & ContentIdea) | ({ kind: "draft" } & Draft);
export type Board = Record<string, BoardCard[]>;

export type RawMaterial = {
  id: string;
  kind: "story" | "quote" | "number" | "failure" | "mentor" | "opinion";
  text: string;
  people: string[];
  date: string | null;
  can_name: boolean;
  confidentiality: "public" | "vague-only" | "private";
  origin?: string | null;
};

export type SeriesRow = { id: string; name: string; platform: string; cadence: string; template: string; slot: string };

export type CalendarData = {
  start: string;
  days: number;
  scheduled: { id: string; platform: string; at: string }[];
  published: { id: string; platform: string; at: string; url: string }[];
  goals: Record<string, { goal: number; done: number }>;
  series: { id: string; name: string; platform: string; cadence: string; slot: string }[];
  evergreen: Draft[];
};

export type Voice = {
  id: string;
  version: number;
  rules: Record<string, unknown>;
  banned_phrases: string[];
  emoji_set: string[];
  platform_overrides: Record<string, unknown>;
  active: boolean;
  note: string | null;
  history: { version: number; note: string | null; created_at: string }[];
};

export type ReferencePost = { id: string; platform: string; text: string; is_own: boolean; metrics: Record<string, unknown> };

export function textOf(v: Pick<DraftVersion, "body" | "thread"> | null | undefined): string {
  if (!v) return "";
  return v.thread && v.thread.length ? v.thread.join("\n\n") : v.body;
}

export function articleOf(v: DraftVersion | null | undefined): Article | null {
  const s = v?.script as { article?: Article } | null | undefined;
  return s?.article ?? null;
}

export function reelOf(v: DraftVersion | null | undefined): ReelScript | null {
  const s = v?.script as ReelScript | null | undefined;
  return s && "hook" in s && s.hook ? s : null;
}
