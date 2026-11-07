import { Badge } from "@/components/ui/badge";
import { DURABILITY, HYPE, hypeTone, RING } from "@/lib/labels";

export function StoryBadges({
  ring,
  update,
  hype,
  durability,
  exploration,
  degraded,
}: {
  ring: string;
  update?: boolean;
  hype?: string | null;
  durability?: string | null;
  exploration?: boolean;
  degraded?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      <Badge tone={ring === "core" ? "accent" : "muted"}>{RING[ring] ?? ring}</Badge>
      {update && <Badge tone="info">UPDATE</Badge>}
      {hype && (
        <Badge tone={hypeTone(hype)} title="Hype check">
          {HYPE[hype] ?? hype}
        </Badge>
      )}
      {durability && (
        <Badge tone="muted" title="Durability">
          {DURABILITY[durability] ?? durability}
        </Badge>
      )}
      {exploration && (
        <Badge tone="info" title="A deliberate pick from outside your usual topics">
          Outside your usual
        </Badge>
      )}
      {degraded && (
        <Badge tone="warn" title="AI analysis was unavailable; ranked by deterministic scores">
          Degraded
        </Badge>
      )}
    </div>
  );
}
