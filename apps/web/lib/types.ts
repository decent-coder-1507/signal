import type { Citation } from "./citations";

export type Ring = "core" | "adjacent" | "wide";

export type StoryAction = {
  type: "post" | "build" | "learn" | "watch" | "try" | "ignore";
  label: string;
  platform?: string | null;
  angle?: string | null;
  skill?: string | null;
  detail?: string | null;
};

export type BriefStory = {
  story_id: string;
  title: string;
  one_line: string;
  ring: Ring | string;
  score: number;
  why_you: string | null;
  hype_verdict: string | null;
  durability: string | null;
  update: boolean;
  what_changed: string | null;
  actions: StoryAction[];
  post_action: StoryAction | null;
  uncertainty: string[];
  exploration: boolean;
  citations: Citation[];
  degraded: boolean;
};

export type BriefContent = {
  kind: "daily" | "weekend" | "catchup" | string;
  topline: string | null;
  stories: BriefStory[];
  post_suggestion: ({ story_id: string; title: string } & StoryAction) | null;
  build_spark: { idea_id: string; title: string; one_liner: string; type: string; lab_score: number } | null;
  learn: { story_id: string; skill: string | null; label: string | null } | null;
  quick_hits: { story_id: string; title: string; ring: string; one_line: string }[];
  watches: { watch: string; story_id: string; title: string; explanation: string; urgency: string }[];
  cards_due: number;
  quiet: { message: string; deep_dive: { story_id: string; title: string } | null } | null;
  degraded: boolean;
  since?: string;
  generated_at?: string;
};

export type Brief = {
  id: string;
  kind: string;
  period_start: string;
  period_end: string;
  content: BriefContent;
  degraded: boolean;
  opened_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export type HabitSteps = Partial<Record<"brief" | "action" | "cards" | "minimum", string>>;

export type Today = {
  date: string;
  habit: { mode: string; steps: HabitSteps; streak: number; today: string; freezes_left: number };
  brief: Brief | null;
  cards_due: number;
  this_month: Record<string, number>;
  unread_notifications: number;
};

export type Notification = { id: string; kind: string; payload: Record<string, unknown>; created_at: string; read: boolean };

export type StoryCard = {
  id: string;
  title: string;
  ring: string;
  topics: string[];
  final_score: number;
  first_seen: string;
  last_updated: string;
  followed: boolean;
  durability: string | null;
  hype_verdict: string | null;
  update: boolean;
  what_changed: string | null;
  one_line: string;
  why_you: string | null;
};

export type Insight = {
  version: number;
  what_happened: string;
  why_you: string;
  what_changes: string;
  hype_verdict: string;
  hype_reasons: string[] | null;
  durability: string;
  durability_reason: string | null;
  moat_note: string | null;
  open_questions: string[] | null;
  actions: StoryAction[] | null;
  confidence: number | null;
  confidence_reason: string | null;
  reading_time: number | null;
  uncertainty_labels: string[] | null;
  citations: Citation[] | null;
  degraded: boolean;
  prompt_version: string;
  model: string;
  created_at: string;
};

export type TimelineItem = {
  item_id: string;
  title: string;
  url: string;
  source: string;
  tier: number;
  role: string;
  label: string;
  published_at: string | null;
  summary: string | null;
  key_facts: unknown[];
};

export type StoryDetail = {
  story: StoryCard;
  insight: Insight | null;
  timeline: TimelineItem[];
  related: { id: string; title: string }[];
  why: {
    final_score: number;
    weights: Record<string, number> | null;
    penalties: string[];
    excluded: unknown;
    matched_profile: string | null;
    judge: { reason?: string; relevance?: number; matched_goals?: string[]; matched_topics?: string[] } | null;
    sub_scores: Record<string, number | null>;
  };
};

export type FeedbackKind = "useful" | "not_for_me" | "more" | "less" | "wrong" | "known" | "opened" | "saved" | "used";

export type TopicEntry = { name: string; weight: number; keywords?: string[]; [k: string]: unknown };
export type Topics = { core?: TopicEntry[]; adjacent?: TopicEntry[]; wide?: TopicEntry[]; [k: string]: unknown };

export type Profile = {
  id: string;
  role: string;
  goals: string[];
  stack: string[];
  topics: Topics;
  blocked_entities: string[];
  blocked_keywords: string[];
  vanco_context: string | null;
  version: number;
};

export type Source = {
  id: string;
  type: string;
  name: string;
  url: string | null;
  tier: number;
  ring: string;
  topics: string[];
  fetch_every: number;
  enabled: boolean;
  params: Record<string, unknown>;
  health: { flagged?: string | null; consecutive_failures?: number; [k: string]: unknown } | null;
  usefulness: number | null;
  terms_note: string;
  last_fetched_at: string | null;
  items?: number;
};

export type Routine = {
  id: string;
  name: string;
  cron: string;
  timezone: string;
  steps: string[];
  channels: string[];
  enabled: boolean;
  params: Record<string, unknown>;
  last_run_at: string | null;
  next_run_at: string | null;
};

export type Watch = {
  id: string;
  query: string;
  urgency: "instant" | "digest";
  enabled: boolean;
  filters: Record<string, string[]>;
  expires_at: string | null;
  last_triggered: string | null;
  hits: number;
};

export type Settings = { flags: Record<string, boolean>; budget_monthly_usd?: number; [k: string]: unknown };
