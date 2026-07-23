# Host adapter templates

Install scripts stamp `install_stamp.txt` under `templates/<platform>/`.

**Skill 单一来源：** `skills-src/` → `scripts/compile_skills.py` → `generated/<host>/skills/`。  
install 只部署 `generated/`，不部署遗留根目录 `skills/`（见 `skills/DEPRECATED.md`）。

**OpenCode Plugin 唯一源：** 仓内 `opencode-plugin/` → `~/.config/opencode/plugins/`。  
本目录**不**存放 Plugin 实现。

**Primary Agent：** `agents/ascendc-agent.md`（`mode: primary`）→ `~/.config/opencode/agents/`。  
默认**不**合并用户 `opencode.json`。威胁模型见 `docs/threat-model.md`。
