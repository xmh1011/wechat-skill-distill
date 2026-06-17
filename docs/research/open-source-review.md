# Open Source Review

This document records product lessons used by `wechat-skill-distill`.

## Reviewed Projects

| Project | Source | Relevant lesson |
| --- | --- | --- |
| wechat-exporter | https://github.com/JettChenT/wechat-exporter | Export tools focus on turning local WeChat history into JSON and documenting platform constraints. `wechat-skill-distill` should consume exported data, not automate WeChat access. |
| chat-history-manager | https://github.com/realdeveloperongithub/chat-history-manager | A parser/generator architecture makes chat tooling extensible across source apps and target formats. |
| WeClone | https://github.com/xming521/weclone | Chat-history-based AI twin tools optimize for style fidelity and identity risk. This product should create auditable skills before considering heavier training workflows. |
| Mem0 | https://github.com/mem0ai/mem0 | Memory products need local, self-hosted, and cloud paths, plus stable user/session/agent metadata. |
| LangMem | https://github.com/langchain-ai/langmem | Long-term memory includes extraction, prompt adaptation, hot-path search, and background consolidation, not only storage. |
| Graphiti | https://github.com/getzep/graphiti | Temporal context and provenance matter when facts and relationships change over time. |

## Product Implications

- Keep a strict separation between style-only skills and memory-aware chat skills.
- Preserve source, timestamp, participants, tags, and user identifiers in memory exports.
- Make local JSONL the safest default and treat cloud backends as adapters.
- Keep parser, normalizer, memory backend, and skill generator as independent modules.
- Add future quality gates for identity leakage, privacy leakage, and style coverage.
