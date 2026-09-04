import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_DETAIL_ROUNDS,
  DEFAULT_ROUNDS,
  extractIndexAsset,
  extractMappings,
  validateSelectedMappings,
} from "../scripts_pipeline/crawl_jp_official.mjs";


const fixture = `
  "../../assets/data/results/22/character/1.json":()=>s(()=>import("./1-char.js"),[]),
  "../../assets/data/results/22/music/1.json":()=>s(()=>import("./1-music.js"),[]),
  "../../assets/data/results/22/work/1.json":()=>s(()=>import("./1-work.js"),[]),
  "../../assets/data/results/22/character/1.json":()=>s(()=>import("./1-char.js"),[]),
  "../assets/data/results/22/character.json":()=>s(()=>import("./character.js"),[]),
  "../assets/data/results/22/music.json":()=>s(()=>import("./music.js"),[]),
  "../assets/data/results/22/work.json":()=>s(()=>import("./work.js"),[]),
  "../assets/data/results/22/count.json":()=>s(()=>import("./count.js"),[]),
  "../assets/data/results/22/questionnaire.json":()=>s(()=>import("./questionnaire.js"),[])
`;


test("round 22 is part of the default modern scope", () => {
  assert.deepEqual(DEFAULT_ROUNDS, [17, 18, 19, 20, 21, 22]);
  assert.deepEqual(DEFAULT_DETAIL_ROUNDS, [17, 18, 19, 20, 21, 22]);
});


test("the current one-level aggregate and two-level detail imports are discovered", () => {
  const mappings = extractMappings(fixture);
  assert.equal(mappings.length, 8);
  assert.deepEqual(
    mappings.reduce((counts, item) => {
      const key = `${item.kind}:${item.category}`;
      counts[key] = (counts[key] ?? 0) + 1;
      return counts;
    }, {}),
    {
      "detail:character": 1,
      "detail:music": 1,
      "detail:work": 1,
      "aggregate:character": 1,
      "aggregate:music": 1,
      "aggregate:work": 1,
      "aggregate:count": 1,
      "aggregate:questionnaire": 1,
    },
  );
  assert.doesNotThrow(() =>
    validateSelectedMappings(mappings, { rounds: [22], detailRounds: [22] }),
  );
});


test("an incomplete publishing wave is rejected before any manifest is certified", () => {
  const mappings = extractMappings(
    fixture.replace(
      '"../assets/data/results/22/questionnaire.json":()=>s(()=>import("./questionnaire.js"),[])',
      "",
    ),
  );
  assert.throws(
    () => validateSelectedMappings(mappings, { rounds: [22], detailRounds: [22] }),
    /lacks round 22 aggregate questionnaire/,
  );
});


test("the result page index asset is found", () => {
  assert.equal(
    extractIndexAsset(
      '<html><script type="module" src="/assets/index-Cpqe1jcA.js"></script></html>',
    ),
    "https://toho-vote.info/assets/index-Cpqe1jcA.js",
  );
});
