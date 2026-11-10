---
name: answer-eye-questions-with-visionkb-kg
description: Test stand-in for the released skill (the image bakes the real v0.2.1 SKILL.md).
metadata:
  version: "0.0.0-test"
---

# Answer eye knowledge questions with the VisionKB knowledge graph (test stand-in)

Resolve names with search_entities, read edges with get_relationships, open evidence with get_evidence, and cite
kg_release and edge_id for every claim. Page with paging.next_offset. This file exists only for the unit tests; the
container image contains the released SKILL.md, verified against the release SHA256SUMS at build time.
