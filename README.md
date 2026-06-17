# wechat-skill-distill

Distill WeFlow-exported WeChat private chats into:

- per-user style-only skills
- memory backend imports
- memory-aware chat skills

The toolkit is backend-neutral. Hindsight, Mem0, JSONL, and generic HTTP are treated as memory adapters.

## What It Does

1. Parse WeFlow JSON exports.
2. Extract one independent style-only skill per participant.
3. Import chat records into a memory backend.
4. Generate chat skills that know how to recall memory.
5. Keep secrets out of generated files and git.

## File Types

This toolkit intentionally generates two different skill artifacts:

| Command | Output | Memory section | Use case |
| --- | --- | --- | --- |
| `extract-skills` | `Participant A.skill` | No | Style-only prompting, manual review, offline role voice. |
| `generate-chat-skills` | `Participant A.chat-memory.skill` | Yes | Agent chats that should recall facts from JSONL, Hindsight, Mem0, or generic HTTP memory. |

## Install

```bash
git clone <your-repo-url> wechat-skill-distill
cd wechat-skill-distill
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
cp config.example.json config.local.json
```

Edit `.env` and `config.local.json` locally. Do not commit them.

## Participant Mapping

WeFlow exports usually contain `isSend`, `senderUsername`, and `senderDisplayName`.
This toolkit does not assume who the users are. Configure participants in `config.local.json`:

```json
{
  "participants": {
    "0": { "user_id": "friend", "name": "Friend" },
    "1": { "user_id": "me", "name": "Me" }
  }
}
```

Keys can be either WeFlow `isSend` values (`"0"`, `"1"`) or exact `senderUsername` values.

## WeFlow Export

This project does not automate WeChat itself. Use WeFlow to export a private chat as JSON, then verify:

```bash
wechat-skill-distill weflow-guide
wechat-skill-distill inspect --input examples/chat.json --config config.local.json
wechat-skill-distill doctor --input examples/chat.json --config config.local.json
```

`inspect` shows raw/importable/skipped message counts, date range, participants, message type distribution, and skip reasons. Use `--json` for automation or `--output reports/inspect.json` to save the report.

## Redact Sensitive Values

```bash
wechat-skill-distill redact \
  --input examples/chat.json \
  --output data/chat.redacted.json \
  --report reports/redaction.json
```

Default rules mask common phone numbers, emails, URLs, mainland China ID card numbers, and bank-card-like numbers. Provide `--policy config/redaction.json` to use custom regex rules.

## Generate Style Skills

```bash
wechat-skill-distill extract-skills \
  --input examples/chat.json \
  --out-dir generated-skills \
  --config config.local.json
```

Outputs look like:

```text
generated-skills/Participant A.skill
generated-skills/Participant B.skill
```

Each skill is independent and contains only that user’s style profile and examples. It does not contain a memory backend, recall instructions, or API key references.

## Import Memory

### Local JSONL Dry Run

```bash
wechat-skill-distill import \
  --backend jsonl \
  --input examples/chat.json \
  --group-by message \
  --output exports/memory.jsonl \
  --dry-run \
  --config config.local.json
```

### Hindsight

```bash
set -a && source .env && set +a
wechat-skill-distill import \
  --backend hindsight \
  --input examples/chat.json \
  --group-by day \
  --config config.local.json
```

### Mem0

Install the optional client first:

```bash
pip install -e '.[mem0]'
```

Then run:

```bash
set -a && source .env && set +a
wechat-skill-distill import \
  --backend mem0 \
  --input examples/chat.json \
  --group-by message \
  --config config.local.json
```

### Generic HTTP

```bash
export MEMORY_WRITE_URL='https://memory.example.com/import'
export MEMORY_API_KEY='...'

wechat-skill-distill import \
  --backend generic-http \
  --input examples/chat.json \
  --group-by day \
  --config config.local.json
```

The generic adapter POSTs:

```json
{
  "items": [
    {
      "content": "...",
      "metadata": {},
      "tags": []
    }
  ]
}
```

## Generate Memory-Aware Chat Skills

```bash
wechat-skill-distill generate-chat-skills \
  --input examples/chat.json \
  --out-dir generated-chat-skills \
  --memory-backend jsonl \
  --config config.local.json
```

Use `--memory-backend hindsight`, `mem0`, or `generic-http` to generate backend-specific recall instructions.

Outputs look like:

```text
generated-chat-skills/Participant A.chat-memory.skill
generated-chat-skills/Participant B.chat-memory.skill
```

## Simulate Chat With A Model

```bash
wechat-skill-distill chat-ui --host 127.0.0.1 --port 8765 --env-file .env --skill generated-chat-skills/Participant A.chat-memory.skill
```

Open the printed URL and chat with the preloaded persona. Pass `--skill` multiple times to preload multiple personas. The page calls the local `chat-ui` server, and the server calls the configured model provider. API keys stay in `.env` or environment variables and are never sent to the browser.

If a runtime memory backend is configured, `/api/chat` recalls relevant memories before calling the model and injects those hits with the selected skill. Raw memory hits are not returned to the browser, and the browser does not upload memory files or run its own retrieval. The UI only shows whether related context was referenced. The recall adapter stays generic; factual boundaries are enforced by the generated `.chat-memory.skill` and the server-side companion prompt.

Recall backend selection defaults to `auto`: Hindsight is used when `HINDSIGHT_API_KEY` is present, otherwise Generic HTTP when `MEMORY_RECALL_URL` is present, otherwise Mem0 when `MEM0_API_KEY` is present, otherwise JSONL when `JSONL_MEMORY_PATH` is present. Set `WSD_MEMORY_RECALL_BACKEND=off` to disable server-side recall.

```bash
WSD_MEMORY_RECALL_BACKEND=auto
WSD_MEMORY_RECALL_MODE=auto
WSD_MEMORY_RESULT_LIMIT=24
WSD_MEMORY_MAX_TOKENS=3200
WSD_MEMORY_QUERY_VARIANTS=1
```

Hindsight recall:

```bash
HINDSIGHT_API_URL=https://cloud.memory.bj.baidubce.com/api
HINDSIGHT_BANK_ID=your-chat-bank
HINDSIGHT_API_KEY=...
WSD_HINDSIGHT_TYPES=world,observation
WSD_HINDSIGHT_MAX_TOKENS=3200
```

Generic HTTP recall:

```bash
MEMORY_RECALL_URL=https://memory.example.com/recall
MEMORY_API_KEY=...
```

The Generic HTTP recall endpoint receives `query`, `queries`, `user_id`, `persona`, `history`, `tags`, `limit`, and `max_tokens`, and should return either a list or an object with `results`, `memories`, `data`, or `items`. Each item may use `text`, `content`, `memory`, or `value` for the memory text.

Mem0 recall:

```bash
pip install -e '.[mem0]'
MEM0_API_KEY=...
```

JSONL recall:

```bash
JSONL_MEMORY_PATH=exports/memory.jsonl
```

Recall runs in `auto` mode by default: lightweight greetings do not query memory, factual turns build a query from the current message, necessary recent user questions, and the active persona. The harness uses a 默认单 query policy；排序和 rerank 交给记忆后端。Hindsight-specific recall first tries strict `user:<id>` scoped recall, then falls back to the skill's conversation tags when the strict pass returns no facts. Other backends receive the same user/persona/query contract and keep their own ranking order. If `WSD_MEMORY_QUERY_VARIANTS` is explicitly set above `1`, Generic HTTP receives all variants in one request through `queries`; Hindsight and Mem0 should usually stay on one precise query so their own ranking remains authoritative.

Supported model protocols:

| Provider | Env vars | Notes |
| --- | --- | --- |
| `openai` | `WSD_OPENAI_BASE_URL`, `WSD_OPENAI_MODEL`, `WSD_OPENAI_API_KEY` | OpenAI-compatible chat completions. Works with OpenAI, OneAPI, DeepSeek-compatible gateways, and similar services. |
| `anthropic` | `WSD_ANTHROPIC_BASE_URL`, `WSD_ANTHROPIC_MODEL`, `WSD_ANTHROPIC_API_KEY` | Anthropic Messages API. |
| `gemini` | `WSD_GEMINI_BASE_URL`, `WSD_GEMINI_MODEL`, `WSD_GEMINI_API_KEY` | Gemini `generateContent` API. |

Keyboard behavior:

- `Enter` sends the message.
- `Shift+Enter` inserts a new line.

## Evaluate Skills

```bash
wechat-skill-distill evaluate-skills \
  --skills generated-skills generated-chat-skills \
  --input examples/chat.json \
  --config config.local.json \
  --output reports/quality.json
```

The evaluator checks required sections, style-only vs memory-aware file type rules, userID markers, participant-name leakage, and verbatim source text outside the sample section. Use `--fail-on-issue` in automation.

## Safety

- `.env`, raw chat exports, generated exports, logs, and runs are ignored.
- API keys are read from environment variables or local config only.
- Use `--dry-run` before writing to a remote memory backend.

## Development Checks

```bash
python3 -m unittest discover -s tests
wechat-skill-distill inspect --input examples/chat.json --config config.local.json
wechat-skill-distill redact --input examples/chat.json --output data/chat.redacted.json --report reports/redaction.json
wechat-skill-distill doctor --input examples/chat.json --config config.local.json
wechat-skill-distill extract-skills --input examples/chat.json --out-dir generated-skills --config config.local.json
wechat-skill-distill generate-chat-skills --input examples/chat.json --out-dir generated-chat-skills --memory-backend jsonl --config config.local.json
wechat-skill-distill import --backend jsonl --input examples/chat.json --output exports/memory.jsonl --dry-run --config config.local.json
wechat-skill-distill chat-ui --host 127.0.0.1 --port 8765
wechat-skill-distill evaluate-skills --skills generated-skills generated-chat-skills --input examples/chat.json --config config.local.json
```

## Product Notes

- [PRD.md](PRD.md) defines the product scope, scenarios, CLI contract, and roadmap.
- [docs/research/open-source-review.md](docs/research/open-source-review.md) records the open-source projects reviewed while shaping this product.
