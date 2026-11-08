import { describe, expect, it } from "vitest";
import { reviewKey, reviewReducer } from "../card-review";
import { missingSteps, nextStepIndex, sectionFor, sectionKeyFor, stepTitle } from "../reviews";

describe("review flow ↔ section mapping", () => {
  it("maps weekly and monthly step keys to their section keys", () => {
    expect(["recap", "content_plan", "idea", "learn", "quiz", "metrics"].map(sectionKeyFor)).toEqual([
      "recap",
      "content_plan",
      "idea_of_week",
      "learn_next",
      "quiz",
      "metrics",
    ]);
    expect(["state_of_tech", "moat", "content", "ideas", "skills", "tuning", "costs"].map(sectionKeyFor)).toEqual([
      "state_of_tech",
      "moat_radar",
      "content_learnings",
      "idea_pipeline_review",
      "skill_progress",
      "tuning",
      "costs",
    ]);
  });

  it("finds sections, titles and progress", () => {
    const content = {
      flow: ["recap", "idea", "learn"],
      done_steps: ["recap"],
      sections: [
        { key: "recap", title: "Week recap" },
        { key: "idea_of_week", title: "Idea & try-it of the week" },
      ],
    };
    expect(sectionFor(content, "idea")?.title).toBe("Idea & try-it of the week");
    expect(sectionFor(content, "learn")).toBeUndefined();
    expect(stepTitle("learn")).toBe("Learn next");
    expect(nextStepIndex(content)).toBe(1);
    expect(missingSteps(content)).toEqual(["idea", "learn"]);
    expect(nextStepIndex({ flow: ["a"], done_steps: ["a"] })).toBe(0);
  });
});

describe("card review keyboard", () => {
  it("reveals with space, rates 1–4 only after reveal", () => {
    expect(reviewKey(" ", false)).toEqual({ type: "reveal" });
    expect(reviewKey("3", false)).toBeNull();
    expect(reviewKey("3", true)).toEqual({ type: "rate", rating: 3 });
    expect(reviewKey("5", true)).toBeNull();
    expect(reviewKey(" ", false, true)).toBeNull();
  });

  it("advances to the next card hidden after a rating", () => {
    let s = { index: 0, revealed: false, reviewed: 0 };
    s = reviewReducer(s, { type: "reveal" });
    expect(s.revealed).toBe(true);
    s = reviewReducer(s, { type: "rated" });
    expect(s).toEqual({ index: 1, revealed: false, reviewed: 1 });
    expect(reviewReducer(s, { type: "reset" })).toEqual({ index: 0, revealed: false, reviewed: 0 });
  });
});
