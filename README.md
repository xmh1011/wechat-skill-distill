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
wechat-skill-distill chat-ui --host 127.0.0.1 --port 8765 --env-file .env
```

Open the printed URL, load one or more `.skill` / `.chat-memory.skill` files, optionally load a `memory.jsonl`, then chat with the selected persona. The page calls the local `chat-ui` server, and the server calls the configured model provider. API keys stay in `.env` or environment variables and are never sent to the browser.

If Hindsight recall is configured, `/api/chat` recalls relevant memories before calling the model and injects those hits with the selected skill. The recall adapter stays generic; factual boundaries are enforced by the generated `.chat-memory.skill` and the server-side companion prompt.

```bash
WSD_MEMORY_RECALL_BACKEND=hindsight
HINDSIGHT_API_URL=https://cloud.memory.bj.baidubce.com/api
HINDSIGHT_BANK_ID=your-chat-bank
HINDSIGHT_API_KEY=...
WSD_HINDSIGHT_TYPES=world,observation
WSD_HINDSIGHT_MAX_TOKENS=1800
```

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
