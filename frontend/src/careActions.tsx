import {
  Beef,
  Bed,
  BookHeart,
  Milk,
  Pill,
  Ruler,
  Scale,
  TestTubeDiagonal,
} from "lucide-react";
import type { AriaAttributes, ComponentType } from "react";

import type { CareRecordCreate, QuickActionPreference } from "./api/types";

export type CareActionKind = CareRecordCreate["record_type"];
type ActionIcon = ComponentType<Pick<AriaAttributes, "aria-hidden">>;

export interface CareAction {
  kind: CareActionKind;
  label: string;
  icon: ActionIcon;
}

function BabyDiaperIcon(_props: Pick<AriaAttributes, "aria-hidden">) {
  return <span aria-hidden="true" className="emoji-icon">◡</span>;
}

export const careActions: CareAction[] = [
  { kind: "breastfeeding", label: "Breastfeed", icon: Milk },
  { kind: "bottle_feeding", label: "Bottle feeding", icon: TestTubeDiagonal },
  { kind: "solid_food_feeding", label: "Solid food", icon: Beef },
  { kind: "sleep", label: "Sleep", icon: Bed },
  { kind: "diaper_change", label: "Diaper change", icon: BabyDiaperIcon },
  { kind: "pumping", label: "Pumping", icon: Scale },
  { kind: "measurement", label: "Measurement", icon: Ruler },
  { kind: "medication_administration", label: "Medicine", icon: Pill },
  { kind: "note", label: "Note", icon: BookHeart },
];

const actionsByKind = new Map<CareActionKind, CareAction>(
  careActions.map((action) => [action.kind, action]),
);

export function orderedCareActions(
  preferences?: QuickActionPreference[],
): CareAction[] {
  if (!preferences) return careActions;
  return preferences
    .filter((preference) => !preference.is_hidden)
    .map((preference) => actionsByKind.get(preference.record_type))
    .filter((action): action is CareAction => action !== undefined);
}

export function careAction(kind: CareActionKind): CareAction {
  const action = actionsByKind.get(kind);
  if (!action) throw new Error(`Unknown care action: ${kind}`);
  return action;
}
