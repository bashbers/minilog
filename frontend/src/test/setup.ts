import "@testing-library/jest-dom/vitest";
import "fake-indexeddb/auto";
import { afterEach, vi } from "vitest";

afterEach(() => {
  vi.restoreAllMocks();
});
