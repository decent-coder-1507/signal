import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CitedText } from "@/components/cited-text";
import { citationIndex, parseCitations, stripCitations } from "../citations";

const A = "0193a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b";
const B = "0193a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a6c";
const cites = [
  { id: A, url: "https://nimbus.example/post", source: "Nimbus Blog", title: "Nimbus-4 launch" },
  { id: B, url: "https://news.example/x", source: "Tech News" },
];

describe("parseCitations", () => {
  it("numbers markers by citation order and keeps surrounding text", () => {
    const idx = citationIndex(cites);
    const segs = parseCitations(`Nimbus shipped a model [${B}]. It is fast [${A}].`, idx);
    expect(segs).toEqual([
      { kind: "text", text: "Nimbus shipped a model" },
      { kind: "cite", ref: { ...cites[1], n: 2 } },
      { kind: "text", text: ". It is fast" },
      { kind: "cite", ref: { ...cites[0], n: 1 } },
      { kind: "text", text: "." },
    ]);
  });

  it("drops unresolvable ids and collapses adjacent duplicates", () => {
    const idx = citationIndex(cites);
    const segs = parseCitations(`Claim [${A}] [${A}] and [ffffffff-0000-0000-0000-000000000000] more [r:${B}]`, idx);
    expect(segs.filter((s) => s.kind === "cite")).toHaveLength(2);
    expect(segs.map((s) => (s.kind === "text" ? s.text : `#${s.ref.n}`)).join("")).toBe("Claim#1 and more#2");
  });

  it("handles empty input and strips markers for plain text", () => {
    expect(parseCitations(null, new Map())).toEqual([]);
    expect(stripCitations(`One [${A}]. Two [${B}].`)).toBe("One. Two.");
  });
});

describe("<CitedText>", () => {
  it("renders footnotes as superscript links with a tooltip, never raw ids", () => {
    const { container } = render(<CitedText text={`Fact [${A}].`} index={citationIndex(cites)} />);
    const a = container.querySelector("sup.cite a") as HTMLAnchorElement;
    expect(a.textContent).toBe("[1]");
    expect(a.href).toBe("https://nimbus.example/post");
    expect(a.title).toBe("Nimbus Blog — Nimbus-4 launch");
    expect(container.textContent).not.toContain(A);
  });
});
