# Progress Visibility Protocol

浣犳槸 `understand-operator` 鐨勫涓?orchestrator銆?*鐢ㄦ埛蹇呴』鍦ㄥ綋鍓嶅璇濋噷鐪嬪埌杩涘害**锛屼絾榛樿涓嶈涓€姝ヤ竴纭锛涜繛缁墽琛屽埌浜哄伐瀹℃牳鐐瑰啀鍋滄銆?

## 榛樿璇█锛堝己鍒讹級

**鏁翠釜椤圭洰榛樿璇█涓轰腑鏂囥€?*

- TodoWrite 鐨?`content` / title锛?*蹇呴』涓枃**锛堢姝㈣嫳鏂?todo 鏍囬锛?
- **闂搁棬**瀵硅瘽锛氬闃呮憳瑕併€丼TOP 鎻愮ず銆佽彍鍗曢€夐」璇存槑锛?*蹇呴』涓枃**
- 鎶€鏈爣璇嗙鍙繚鐣欒嫳鏂囷紙濡?`uo-p0`銆佹枃浠惰矾寰勩€乣search_graph`銆乫amily_id锛?
- 涓嶈鍐?鈥渨hen user asks for Chinese鈥?鈥斺€?涓枃鏄粯璁わ紝涓嶆槸鍙€夐」
- 闈為椄闂?phase锛?*涓嶈**涓轰簡銆岃繘搴﹀彲瑙併€嶈€岃緭鍑洪暱涓枃瀹￠槄鍧楋紱TodoWrite 鍗冲彲

## 涓轰粈涔堜箣鍓嶄細銆岄粯榛樿窇銆?

甯歌鍘熷洜锛堝繀椤婚伩鍏嶏級锛?

1. 瀹夸富杩炵画鍋氬涓?phase 鏃讹紝**涓嶆洿鏂?TodoWrite**锛堣繘搴﹀簲闈?todo list锛岃€屼笉鏄瘡姝ュ埛瀹￠槄闀挎枃锛夈€?
2. 鐢ㄤ簡 **background Task / background shell**锛孶I 鍙樉绀?鈥淢onitored background task鈥濓紝鐢ㄦ埛鐪嬩笉鍒伴樁娈靛垪琛ㄣ€?
3. **娌℃湁鍒涘缓 Cursor todo list**锛圱odoWrite锛夈€?
4. Phase 0 璺戝畬鐩存帴杩涘叆 Phase 1锛?*娌℃湁鍏堢粡杩?0.5 闂搁棬**銆?
5. 鎶?subagent 杩斿洖鎽樿褰撴垚瀹屾垚锛?*娌℃湁 barrier + 杩涘害鏇存柊**銆?
6. Todo 鏍囬鍐欐垚鑻辨枃锛堝 `Phase 0 鈥?Preflight`锛夆€斺€?**绂佹**銆?
7. Phase 1 缁撴潫鍚庡張璐翠竴娈?Boundary/IO銆屽闃呫€嶆枃瀛椻€斺€?**绂佹**锛堥偅涓嶆槸闂搁棬锛夈€?

## 寮哄埗瑙勫垯

### 1. 鍚姩鍚庣涓€浠朵簨锛氬垱寤轰腑鏂?Todo List

璇诲彇 skill 鍚庛€佹墽琛屼换浣?phase 涔嬪墠锛?*蹇呴』**璋冪敤 **TodoWrite** 鍒涘缓瀹屾暣浠诲姟鍒楄〃锛坢erge=false锛夈€?

鍥哄畾 todo id 涓?**涓枃 content**锛堜竴瀛椾笉宸紭鍏堢敤涓嬭〃锛夛細

| id | content锛圱odoWrite 鏄剧ず鏂囨锛屽繀椤讳腑鏂囷級 |
|---|---|
| `uo-p0` | 闃舵 0 鈥?棰勬甯冨眬涓?MCP 鑷姩绱㈠紩 |
| `uo-p05` | 闃舵 0.5 鈥?瀹忚鎵ц鑼冨洿浜哄伐瀹￠槄锛堥椄闂級 |
| `uo-p1` | 闃舵 1 鈥?瀹忚杈圭晫鍒嗘瀽 |
| `uo-p2a` | 闃舵 2a 鈥?骞惰涓嬪彂 host 涓?flow 瀛愪唬鐞?|
| `uo-p2b` | 闃舵 2b 鈥?灞忛殰鏍￠獙骞惰鍙?tiling/flow |
| `uo-p3` | 闃舵 3 鈥?Kernel 浠诲姟瑙勫垝 |
| `uo-p35` | 闃舵 3.5 鈥?Kernel 鍒嗗彂浜哄伐瀹￠槄锛堥椄闂紝鍚叏閲?tiling/family锛?|
| `uo-p4a` | 闃舵 4a 鈥?骞惰涓嬪彂 kernel path 瀛愪唬鐞?|
| `uo-p4b` | 闃舵 4b 鈥?灞忛殰鏍￠獙骞惰鍙?kernel paths |
| `uo-p5` | 闃舵 5 鈥?Kernel 瀵归綈鐭╅樀 |
| `uo-p6` | 闃舵 6 鈥?璇佹嵁涓€鑷存€у璁?|
| `uo-p7` | 闃舵 7 鈥?璺敱涓庣煡璇嗗簱鍦板浘 |
| `uo-p8` | 闃舵 8 鈥?璐ㄩ噺闂ㄧ |

> **涓嶈**鍒涘缓 `uo-p15`銆傞樁娈?1.5 宸插彇娑堛€?

TodoWrite 绀轰緥锛堝惎鍔ㄦ椂 merge=false锛夛細

```text
uo-p0  闃舵 0 鈥?棰勬甯冨眬涓?MCP 鑷姩绱㈠紩          pending
uo-p05 闃舵 0.5 鈥?瀹忚鎵ц鑼冨洿浜哄伐瀹￠槄锛堥椄闂級    pending
uo-p1  闃舵 1 鈥?瀹忚杈圭晫鍒嗘瀽                    pending
...锛堝叾浣欏悓涓婅〃锛屽叏閮?pending锛?
```

### 2. 姣忎釜 phase 鐨勬爣鍑嗚妭濂?

瀵规瘡涓?todo item锛?

1. **寮€濮嬪墠**锛歍odoWrite 鈫?璇ラ」 `in_progress`銆傞潪闂搁棬 phase **涓嶈**鍦ㄥ璇濋噷鍐欓暱璇存槑銆?
2. **瀹屾垚鍚庯紙闈為椄闂級**锛歍odoWrite 鈫?璇ラ」 `completed`锛涙洿鏂?`workflow_progress.yaml`锛?*绔嬪埢缁х画涓嬩竴 phase**銆傚璇濋噷鏈€澶氫竴琛屾瀬绠€鐘舵€侊紙鍙渷鐣ワ級锛?*绂佹**杈撳嚭 IO/杈圭晫/open_questions/family 绛夊闃呭紡鎽樿銆?
3. **闂搁棬 phase锛堜粎 0.5 / 3.5锛?*锛歵odo 淇濇寔 `in_progress` 鎴?waiting锛?*蹇呴』 STOP 绛夌敤鎴?*銆傛鏃舵墠灞曠ず瀹屾暣銆佸彲渚涗汉鍒ゆ柇鐨勫闃呮憳瑕?+ 閫夋嫨 UI銆備紭鍏堢敤 OpenCode `question` / Cursor AskQuestion锛堟渶鍚庝竴椤瑰彲杈撳叆鎵嬪伐琛ュ厖锛夛紝鍐嶇敤 `review_checkpoint.py --decision` 钀界洏銆傞樁娈?3.5 鎽樿蹇呴』鍚畬鏁?tiling/family 淇℃伅锛堜腑鏂囷級銆?

### 2.1 瀵硅瘽杈撳嚭鍒嗘祦锛堝己鍒讹級

| 鍦烘櫙 | 瀵硅瘽閲屽厑璁歌緭鍑?| 鏄惁 STOP |
|---|---|---|
| 鏅€?phase锛堝惈闃舵 1 瀹忚杈圭晫锛?| TodoWrite锛涘彲閫変竴琛屻€岄樁娈?X 瀹屾垚 鈫?杩涘叆 Y銆?| **鍚?* |
| Subagent 涓嬪彂 / barrier | 涓€鍙ャ€屽凡鍚姩/灞忛殰閫氳繃銆?| **鍚?* |
| **闂搁棬 0.5 / 3.5** | 瀹屾暣瀹￠槄鎽樿锛堢粰浜哄垽鏂級+ 閫夋嫨鑿滃崟 | **鏄?* |

**绂佹**鍦ㄩ潪闂搁棬澶勮緭鍑猴細Boundary/IO 鎽樿銆乷pen_questions 鍒楄〃銆乫amily 琛ㄣ€佽纭/璇峰闃呯被鏂囨銆佸亣瑁呯瓑浜虹殑銆屼笅涓€姝ヨ纭銆嶃€傝繖浜涘唴瀹瑰彧鍐欒繘 artifact锛堝 `operator.yaml` / `human/review.md`锛夛紝涓嶅埛鑱婂ぉ銆?

### 3. 榛樿杩炵画鎵ц鍒颁汉宸ュ鏍哥偣

| 绫诲瀷 | 鏈洖鍚堝厑璁?|
|---|---|
| 鏅€氬涓?phase | 鍙互杩炵画鎵ц澶氫釜 phase锛岀洿鍒颁笅涓€涓汉宸ュ鏍哥偣锛?*涓?*鍚戠敤鎴峰€惧€掑闃呮潗鏂?|
| subagent 涓嬪彂 / barrier | 鍙互鍦?subagent 鍏ㄩ儴杩斿洖鍚庣户缁窇 barrier锛涘繀椤诲厛 barrier 閫氳繃鍐嶈浜х墿 |
| 闂搁棬 turn | **浠呮澶?*灞曠ず瀹￠槄鎽樿 + 绛夌敤鎴?|

榛樿鍏佽鎵ц鍒般€岄樁娈?0.5 瀹忚鎵ц鑼冨洿瀹￠槄銆嶏紝鐒跺悗**蹇呴』 STOP**銆傜敤鎴?`continue` 鍚庯紝榛樿杩炵画鎵ц銆岄樁娈?1 鈫?2 鈫?3 鈫?3.5銆嶏紝鍦?**3.5** 鍐嶅仠锛堝繀椤诲睍绀哄叏閲?tiling/family锛夈€?*绂佹**瓒婅繃 0.5 / 3.5銆?*绂佹**鍐嶅仠鍦ㄦ棫鐨勯樁娈?1.5銆?*绂佹**闃舵 1 缁撴潫鍚庡啀璐翠竴娈靛畯瑙傝竟鐣?IO 鏂囧瓧鍐嶇户缁€?

### 4. Subagent 蹇呴』 foreground

瀵?`uo-host-extraction`銆乣uo-flow-extraction`銆乣uo-kernel-path`锛?

- Task 蹇呴』 **foreground**锛堥粯璁わ級锛?*绂佹** `run_in_background: true`銆?
- 涓嬪彂鍚庡湪瀵硅瘽鍐欐槑锛歚宸插惎鍔ㄥ瓙浠ｇ悊: ...锛岀瓑寰呰繑鍥炲悗杩涘叆灞忛殰鏍￠獙銆俙
- 鍏ㄩ儴 subagent 杩斿洖鍚庯紝蹇呴』鍏堣繍琛?barrier锛沚arrier 閫氳繃鍚庢墠鑳界户缁悗缁?phase銆?

### 5. 鎸佷箙鍖栬繘搴︽枃浠?

姣忎釜 phase 瀹屾垚鍚庢洿鏂?`$UO_ROOT/archive/runs/workflow_progress.yaml`锛?

```yaml
op_name: <OP_NAME>
updated_at: <ISO8601>
current_phase: <id>
language: zh-CN
todos:
  - id: uo-p0
    title: 闃舵 0 鈥?棰勬甯冨眬涓?MCP 鑷姩绱㈠紩
    status: completed
  - id: uo-p1
    title: 闃舵 1 鈥?瀹忚杈圭晫鍒嗘瀽
    status: in_progress
notes: "<绠€鐭腑鏂囪鏄?"
```

### 6. 瀵硅瘽鍐呰繘搴﹀潡妯℃澘锛堜腑鏂囷級

**浠呴椄闂?turn锛?.5 / 3.5锛?*浣跨敤瀹屾暣杩涘害鍧楋紱鏅€?phase **涓嶈**姣忔璐磋繖涓ā鏉裤€?

闂搁棬妯℃澘锛?

```markdown
## 杩涘害 路 <闂搁棬涓枃鍚嶇О>
- 鐘舵€? 绛夊緟鐢ㄦ埛
- 浜х墿: `<鐩稿 UO_ROOT 鐨勮矾寰?`
- 涓嬩竴姝? <鏄庣‘涓€鍙ヤ腑鏂囷紝璇存槑闇€瑕佺敤鎴峰喅绛栦粈涔?
```

鍏跺悗蹇呴』绱ц窡鍙緵浜哄垽鏂殑瀹￠槄姝ｆ枃锛?.5 瑙?`01a`锛?.5 瑙?`05a`锛変笌閫夋嫨 UI銆?

鏅€?phase 瀹屾垚鍚庯細鍙洿鏂?TodoWrite + `workflow_progress.yaml`锛岀洿鎺ュ紑涓嬩竴 phase锛涗笉瑕佽创銆岃繘搴?路 鈥︺€嶉暱鍧椼€?

## 闃舵 0 缁撴潫鍚庣殑鑼冨洿瀹￠槄

闃舵 0 瀹屾垚鍚庡繀椤伙細

1. 鏇存柊 todo `uo-p0` 鈫?completed
2. 鍐欏叆 `runs/<current_run_id>/phase0/scope_review.yaml`
3. 杩涘叆闃舵 0.5锛?*灞曠ず** include / exclude / branch_skip / uncertain_scope锛堢粰浜哄垽鏂級+ 閫夋嫨 UI
4. **STOP 绛夌敤鎴风‘璁?*銆傚彧鏈夌敤鎴烽€夋嫨 `continue` 鍚庯紝鎵嶈繘鍏ラ樁娈?1銆?

闃舵 1锛堝畯瑙傝竟鐣岋級瀹屾垚鍚庯細**涓嶈**鍐嶅悜瀵硅瘽杈撳嚭杈圭晫/IO/open_questions 鎽樿锛汿odoWrite 鏍囧畬鎴愬苟**鐩存帴**杩涘叆闃舵 2銆?

