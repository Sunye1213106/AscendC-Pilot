# Host Adapters

Host adapter 把同一套 Pilot runtime 投影到不同 AI coding hosts。

## 支持的 Host

- OpenCode
- Cursor
- Codex

## 职责

- 为 host 安装 generated skills、agents、prompts、policies 和 hooks。
- 把 host-specific path / syntax 隔离在 adapter 层。
- 在不同 host 上保持同一套 Pilot workflow 与 lease model。

## 非职责

- Host adapter 不拥有领域语义。
- Host adapter 不定义 workflow 权威。
- Generated host instructions 是镜像，不是源文档。

## 实现锚点

- `adapters/hosts/opencode.yaml`
- `adapters/hosts/cursor.yaml`
- `adapters/hosts/codex.yaml`
- `opencode-plugin/`
- `install.ps1`
- `install.sh`
- `refresh-opencode.ps1`
- `scripts/compose_runtime.py`
- `generated/`
