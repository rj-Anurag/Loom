import assert from "node:assert/strict";
import test from "node:test";

import { parseProjectSummary } from "../src/lib/project-summary.ts";

test("parses project overview sections and bullets", () => {
  assert.deepEqual(
    parseProjectSummary(
      "## Overview\n- Aurora is teal [1].\n\n## Decisions\n- Retry limit: seven [2].",
    ),
    [
      { heading: "Overview", items: ["Aurora is teal [1]."] },
      { heading: "Decisions", items: ["Retry limit: seven [2]."] },
    ],
  );
});

test("keeps older plain-text summaries readable", () => {
  assert.deepEqual(parseProjectSummary("Aurora is teal [1]."), [
    { heading: "Overview", items: ["Aurora is teal [1]."] },
  ]);
});
