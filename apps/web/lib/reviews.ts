// Weekly/monthly review flows (§10.1): `content.flow` lists the UI steps; `content.sections` holds what the
// routine generated. Some step keys differ from their section keys, so map them here.

export type ReviewItem = { title: string; href?: string; sub?: string; story_id?: string; platform?: string };
export type ReviewSection = {
  key: string;
  title: string;
  text?: string;
  items?: ReviewItem[];
  proposals?: ReviewItem[];
  data?: unknown;
  [k: string]: unknown;
};
export type ReviewContent = { kind: "weekly" | "monthly"; flow: string[]; done_steps: string[]; sections: ReviewSection[] };
export type Review = { id: string; kind: "weekly" | "monthly"; period_start: string; period_end: string; content: ReviewContent; completed_at: string | null };

const SECTION_FOR_STEP: Record<string, string> = {
  // weekly
  idea: "idea_of_week",
  learn: "learn_next",
  // monthly
  moat: "moat_radar",
  content: "content_learnings",
  ideas: "idea_pipeline_review",
  skills: "skill_progress",
};

const STEP_TITLES: Record<string, string> = {
  recap: "Week recap",
  content_plan: "Content plan",
  idea: "Idea of the week",
  learn: "Learn next",
  quiz: "Quiz",
  metrics: "Metrics & habit",
  state_of_tech: "State of tech",
  moat: "Moat Radar",
  content: "Content learnings",
  ideas: "Idea pipeline",
  skills: "Skill progress",
  tuning: "Tuning proposals",
  costs: "Costs",
};

export function sectionKeyFor(step: string): string {
  return SECTION_FOR_STEP[step] ?? step;
}

export function sectionFor(content: Pick<ReviewContent, "sections">, step: string): ReviewSection | undefined {
  const key = sectionKeyFor(step);
  return content.sections.find((s) => s.key === key);
}

export function stepTitle(step: string, section?: ReviewSection): string {
  return section?.title ?? STEP_TITLES[step] ?? step.replace(/_/g, " ");
}

/** Index of the first step not yet done (or the last step when everything is done). */
export function nextStepIndex(content: Pick<ReviewContent, "flow" | "done_steps">): number {
  const i = content.flow.findIndex((s) => !content.done_steps.includes(s));
  return i < 0 ? Math.max(0, content.flow.length - 1) : i;
}

export function missingSteps(content: Pick<ReviewContent, "flow" | "done_steps">): string[] {
  return content.flow.filter((s) => !content.done_steps.includes(s));
}
