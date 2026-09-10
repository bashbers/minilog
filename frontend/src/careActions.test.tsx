import { describe, expect, it } from "vitest";

import type { QuickActionPreference } from "./api/types";
import { careActions, orderedCareActions } from "./careActions";

describe("orderedCareActions", () => {
  it("uses the product defaults until preferences have loaded", () => {
    expect(orderedCareActions().map((action) => action.kind)).toEqual(
      careActions.map((action) => action.kind),
    );
  });

  it("follows the caregiver order and removes hidden actions", () => {
    const preferences: QuickActionPreference[] = [
      { record_type: "sleep", position: 0, is_hidden: false },
      { record_type: "bottle_feeding", position: 1, is_hidden: true },
      { record_type: "note", position: 2, is_hidden: false },
    ];

    expect(orderedCareActions(preferences).map((action) => action.kind)).toEqual([
      "sleep",
      "note",
    ]);
  });
});
