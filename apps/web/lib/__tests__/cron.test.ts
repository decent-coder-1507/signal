import { describe, expect, it } from "vitest";
import { describeCron, fromCron, looksLikeCron, parseTime, toCron, type CronPreset } from "../cron";

describe("cron builder", () => {
  const cases: [CronPreset, string][] = [
    [{ kind: "weekdays", hour: 7, minute: 30 }, "30 7 * * 1-5"],
    [{ kind: "daily", hour: 13, minute: 0 }, "0 13 * * *"],
    [{ kind: "weekly", dow: 0, hour: 10, minute: 0 }, "0 10 * * 0"],
    [{ kind: "monthly", day: 1, hour: 10, minute: 0 }, "0 10 1 * *"],
  ];

  it.each(cases)("%o ↔ %s", (preset, cron) => {
    expect(toCron(preset)).toBe(cron);
    expect(fromCron(cron)).toEqual(preset);
  });

  it("falls back to raw for anything it cannot represent", () => {
    expect(fromCron("0 10 1 1,4,7,10 *")).toEqual({ kind: "raw", cron: "0 10 1 1,4,7,10 *" });
    expect(fromCron("0 9 * * 6,0")).toEqual({ kind: "raw", cron: "0 9 * * 6,0" });
    expect(fromCron("0 * * * *")).toEqual({ kind: "raw", cron: "0 * * * *" });
    expect(toCron({ kind: "raw", cron: "  0   9 * *  6 " })).toBe("0 9 * * 6");
  });

  it("treats Sunday as 0 or 7", () => {
    expect(fromCron("15 8 * * 7")).toEqual({ kind: "weekly", dow: 0, hour: 8, minute: 15 });
  });

  it("describes schedules in plain words", () => {
    expect(describeCron("30 7 * * 1-5")).toBe("Weekdays at 07:30");
    expect(describeCron("0 10 * * 0")).toBe("Every Sunday at 10:00");
    expect(describeCron("0 10 1 * *")).toBe("1st of every month at 10:00");
    expect(describeCron("30 2 * * *")).toBe("Every day at 02:30");
    expect(describeCron("0 * * * *")).toBe("Custom: 0 * * * *");
  });

  it("parses times and loosely validates cron", () => {
    expect(parseTime("07:30")).toEqual({ hour: 7, minute: 30 });
    expect(parseTime("25:00")).toBeNull();
    expect(looksLikeCron("0 9 * * 6,0")).toBe(true);
    expect(looksLikeCron("every day")).toBe(false);
  });
});
