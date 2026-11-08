import type { Citation } from "./citations";
export const IDEA_STATUSES = ["spark", "shortlisted", "validating", "building", "shipped", "shared", "archived", "killed"] as const;
export type IdeaStatus = (typeof IDEA_STATUSES)[number];

export const IDEA_TYPES = ["practical", "experiment", "poc", "weekend_build", "product", "oss_contribution", "teardown", "vanco"] as const;

export const SCORE_KEYS = ["impact", "confidence", "ease", "personal_fit", "learning_value", "content_value", "novelty"] as const;

export type Idea = {
  id: string;
  type: string;
  title: string;
  one_liner: string;
  evidence: { ref: string; why: string }[] | null;
  problem: string;
  persona: string;
  why_now: string;
  solution: string;
  mvp_scope: string[] | null;
  not_in_mvp: string[] | null;
  stack: string[] | null;
  effort: Record<string, string | number> | null;
  risks: string[] | null;
  moat: string;
  validation_plan: string[] | null;
  learning_skills: string[] | null;
  content_plan: string[] | null;
  scores: Partial<Record<(typeof SCORE_KEYS)[number], number>> | null;
  lab_score: number;
  prior_art: { id: string; title: string; url: string }[] | null;
  status: IdeaStatus | string;
  kill_reason: string | null;
  origin: string;
  created_at: string;
  updated_at: string;
};

export type IdeaDetail = Idea & {
  evidence_links: { title: string; url: string; note: string }[];
  logs: { id: string; text: string; attachments: unknown[]; logged_at: string }[];
  brief: { version: number; files: Record<string, string> } | null;
};

export type SkillNode = {
  id: string;
  name: string;
  durability: string;
  current_level: number;
  target_level: number;
  market_signal: number;
  market_trend: number;
  importance: number;
  children: SkillNode[];
};

export type LearnNext = {
  items: {
    skill: string;
    skill_id: string;
    priority: number;
    why: string;
    evidence: { id: string; title: string }[];
    ignore_instead: string;
    plan: {
      explainer_topic: string;
      resources: { id: string; title: string; url: string }[];
      practical: string;
      time_estimate: string;
      done_definition: string;
    };
  }[];
  ignore: string[];
};

export type GymCard = {
  id: string;
  type: string;
  front: string;
  back: string;
  durability: string | null;
  due_at: string;
  reps: number;
  lapses: number;
  stability: number;
  state: number | string;
};

export type Explainer = {
  id: string;
  topic: string;
  depth: string;
  body: string;
  citations: string[];
  sources: Citation[];
  cards: GymCard[];
};

export type Progress = {
  radar: { domain: string; current: number; target: number }[];
  cards_reviewed_30d: number;
  retention: number | null;
  learning_streak: number;
  concepts_this_month: number;
  time_split: Record<string, number>;
  target_split: Record<string, number>;
  due_now: number;
};

export type MoatPoint = { claim: string; evidence: string[]; reasoning: string };
export type MoatRadar = {
  id: string;
  topic: string | null;
  period_start: string;
  period_end: string;
  commoditising: MoatPoint[];
  appreciating: MoatPoint[];
  for_you: { know: MoatPoint[]; learn: MoatPoint[]; stop: MoatPoint[] };
  for_builders: MoatPoint[];
  predictions?: { text: string; revisit_in_days: number }[];
  evidence: Record<string, { title: string; url: string; story_url: string }>;
  scorecard: {
    total: number;
    resolved: number;
    right: number;
    accuracy: number | null;
    items: { id: string; text: string; made_on: string; revisit_on: string; outcome: string | null }[];
  };
};
