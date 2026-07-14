# CBM On-Demand Query Protocol (MCP)

CBM graph DB 鐢?MCP **`index_repository`** 鐢熸垚骞剁淮鎶ゃ€? 
璇箟鏌ヨ鍦ㄥ悇 phase **鎸夐渶**璋冪敤 **`codebase-memory-mcp` MCP 宸ュ叿**銆?
## 寮哄埗锛氬叏绋?MCP

| 鍦烘櫙 | 鍋氭硶 |
|---|---|
| `/uo-init` Phase 0 寤哄簱 | MCP `index_repository`锛堣嚜鍔紝蹇呭仛锛?|
| `/uo-update` 鍒锋柊 / 鍙樻洿 | MCP `index_repository`锛堣嫢闇€瑕侊級+ `detect_changes` |
| 鏌ョ鍙?/ 鐗囨 / 璋冪敤閾?| MCP `search_graph` / `search_code` / `get_code_snippet` / `trace_path` |
| KB 甯冨眬 | `prepare_operator.py`锛?*涓?*寤?DB锛?|
| 璁板綍 project 鍚?| `prepare_operator.py --write-index-meta --cbm-project ...` |

**绂佹** agent 涓虹储寮曟垨鏌ヨ鍘昏窇锛?
- `cbm_query.py` / `uo-cbm`
- `codebase-memory-mcp cli ...`
- `prepare_operator.py --cli-cbm`锛堥櫎闈炵敤鎴锋槑纭姹傚簲鎬ョ绾匡級

鍏ㄥ眬瑙勫垯瑙?`prompts/common/02_cbm_first_rules.md`銆係etup 瑙?`docs/cbm-mcp-setup.md`銆?
## /uo-init 鑷姩绱㈠紩锛圥hase 0锛?
```text
prepare_operator.py          鈫?鍙缓 .understand-operator/<op>/ 鐩綍
MCP index_repository         鈫?鐢熸垚/鏇存柊 MCP 鏈湴 graph DB
MCP list_projects/index_status 鈫?纭鎴愬姛锛屽彇 project 鍚?prepare_operator.py --write-index-meta --cbm-project <name> 鈫?鍐欏叆 cbm/index_meta.json
```

DB 钀藉湪 MCP 缂撳瓨鐩綍锛堥€氬父 `~/.cache/codebase-memory-mcp/`锛夛紝涓嶆槸鎵嬪啓 SQLite銆? 
`cbm/index_meta.json` 鍙褰?`repo_root` / `cbm_project` / `indexed_via: mcp`锛屾柟渚垮悗缁?phase 瀵归綈銆?
## 甯哥敤 MCP 鏌ヨ宸ュ叿

| 鐩殑 | tool | 鍙傛暟绀轰緥 |
|---|---|---|
| 寤哄簱/鍒锋柊绱㈠紩 | `index_repository` | `repo_path`, `mode`=`fast`\|`full` |
| 鍒楅」鐩?| `list_projects` | 锛堟棤鍙傛垨鎸夋湇鍔＄害瀹氾級 |
| 绱㈠紩鐘舵€?| `index_status` | `repo_path` |
| 鎵剧鍙?| `search_graph` | `name_pattern`, `label` |
| 鎵惧瓧绗︿覆 | `search_code` | `pattern` |
| 鍑芥暟鐗囨 | `get_code_snippet` | qualified `symbol` |
| 璋冪敤閾?| `trace_path` | `function_name`, `depth` |
| 鍙樻洿 | `detect_changes` | `repo_path` |

## 璇佹嵁鑾峰彇椤哄簭

1. 鍏堣皟 MCP  
2. 鎻愬彇绗﹀彿銆佹枃浠躲€佽鍙? 
3. 鎴愬姛鍚庡彲灏忚寖鍥?`Read` 鏍稿  
4. 浠?MCP 澶辫触鎵嶆暣鏂囦欢 `Read` / Grep  
5. 绂佹鏈煡 MCP 灏辫婧愮爜锛涚姝㈢敤 CLI 浠ｆ浛 MCP  

## evidence 鍐欐硶

```yaml
evidence:
  - type: cbm_mcp
    tool: search_graph
    phase: query
    args:
      name_pattern: ".*MyOpTiling.*"
      label: Function
    symbol: MyOpTiling
    file: op_host/my_op_tiling.cpp
    confidence: high
```

## MCP 鏈繛鎺?
1. 鎻愮ず `docs/cbm-mcp-setup.md`  
2. 閰嶇疆 OpenCode / Cursor MCP 鍚庨噸鍚? 
3. **涓嶈**鐢?CLI 绱㈠紩鍚庣户缁亣瑁?MCP 鍙敤  

