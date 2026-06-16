# WeChat Hindsight Importer

Import WeFlow-exported private WeChat chat records into a Hindsight memory bank.

This repository was created for importing the chat between:

- `661`: Hu Xiangchuan
- `662`: Xiao Minghao

The importer keeps the API key out of the repository. Provide it with the
`HINDSIGHT_API_KEY` environment variable or a local `.env` file that is not
committed.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then edit `.env` locally and set `HINDSIGHT_API_KEY`.

## Dry Run

```bash
. .venv/bin/activate
set -a && source .env && set +a
python scripts/import_weflow_to_hindsight.py \
  --input ../私聊_胡翔川.json \
  --dry-run \
  --insecure
```

## Import

The default grouping is one retain item per day. Each item contains all messages
from that day with per-message timestamps in the content, and item metadata
includes both user IDs plus the day start/end timestamps.

```bash
. .venv/bin/activate
set -a && source .env && set +a
python scripts/import_weflow_to_hindsight.py \
  --input ../私聊_胡翔川.json \
  --configure-bank \
  --insecure
```

Use `--group-by message` only when you need one Hindsight document per message.
That preserves each message timestamp as item-level metadata but loses more
conversation context and creates many more documents.

