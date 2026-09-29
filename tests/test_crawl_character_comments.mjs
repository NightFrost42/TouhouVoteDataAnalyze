import assert from "node:assert/strict";
import test from "node:test";

import {
  buildModernEntity,
  normalizeModernComments,
} from "../scripts_pipeline/crawl_jp_character_comments.mjs";


test("modern modules normalize generated comment objects", () => {
  const comments = normalizeModernComments({
    comments: [
      { primary: true, name: "投票者", body: "  霊夢が好き  ", time: "2024-01-01" },
      { primary: false, name: null, body: "魔理沙" },
      { body: "" },
    ],
  });
  assert.deepEqual(comments, [
    {
      text: "霊夢が好き",
      raw_text: "霊夢が好き",
      author: "投票者",
      is_primary: true,
      submitted_at: "2024-01-01",
    },
    {
      text: "魔理沙",
      raw_text: "魔理沙",
      author: null,
      is_primary: false,
      submitted_at: null,
    },
  ]);
});


test("modern entity preserves rank and source provenance", () => {
  const entity = buildModernEntity({
    round: 22,
    id: "101",
    aggregate: { rank: 3, name: "博麗 霊夢" },
    data: { name: "博麗 霊夢", comments: [{ body: "主人公" }] },
    source: { url: "https://example.invalid/101.js", sha256: "abc" },
  });
  assert.equal(entity.region, "jp");
  assert.equal(entity.entity_id, "101");
  assert.equal(entity.entity_name, "博麗 霊夢");
  assert.equal(entity.rank, 3);
  assert.equal(entity.comment_count, 1);
  assert.equal(entity.source.sha256, "abc");
});
