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

## Safety

- `.env`, raw chat exports, generated exports, logs, and runs are ignored.
- API keys are read from environment variables or local config only.
- Use `--dry-run` before writing to a remote memory backend.

## Development Checks

```bash
python3 -m unittest discover -s tests
wechat-skill-distill inspect --input examples/chat.json --config config.local.json
wechat-skill-distill doctor --input examples/chat.json --config config.local.json
wechat-skill-distill extract-skills --input examples/chat.json --out-dir generated-skills --config config.local.json
wechat-skill-distill generate-chat-skills --input examples/chat.json --out-dir generated-chat-skills --memory-backend jsonl --config config.local.json
wechat-skill-distill import --backend jsonl --input examples/chat.json --output exports/memory.jsonl --dry-run --config config.local.json
```

## Product Notes

- [PRD.md](PRD.md) defines the product scope, scenarios, CLI contract, and roadmap.
- [docs/research/open-source-review.md](docs/research/open-source-review.md) records the open-source projects reviewed while shaping this product.
