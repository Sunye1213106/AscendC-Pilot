# 璺緞瑙ｆ瀽锛堝己鍒讹級鈥?绂佹鍏ㄧ洏鎼滅储

OpenCode / Cursor 鎶?skill 瑁呮垚 junction 鍚庯紝agent 甯歌鍒ゃ€屾湰鏈烘病鏈?prepare_operator銆嶏紝鐒跺悗鍘绘壂 `C:\` 鈥斺€?**缁濆绂佹**銆?
## 绂佹

```text
Get-ChildItem C:\ -Recurse -Filter prepare_operator*
鍦ㄦ暣涓鐩?/ 鏁翠釜 PR-review 鏍戦噷鐩叉悳 understand-operator-plugin
鍥犱负銆屾壘涓嶅埌鑴氭湰銆嶅氨鍘昏绠楀瓙 op_kernel 鐩綍鐚滅粨鏋?```

鑴氭湰**涓€瀹氬湪** skill 鏃侊紝涓嶅湪绠楀瓙浠撳簱閲岋紝涔熶笉鍦?`C:\` 鏍逛笅銆?
## 鍙橀噺鎬庝箞绠楋紙鎸夐『搴忥紝鍛戒腑鍗冲仠锛?
璁炬湰 skill 鐩綍涓?`THIS_SKILL`锛堝惈褰撳墠 `SKILL.md` 鐨勭洰褰曪紝鍙负 junction锛夈€?
### 1) SCRIPT_DIR锛堝叡浜剼鏈紝鍚?prepare_operator.py锛?
鎸夐『搴忚瘯锛?*绗竴涓瓨鍦?`prepare_operator.py` 鐨勭洰褰?*鍗充负 `SCRIPT_DIR`锛?
1. `THIS_SKILL/../understand-operator`  
   锛圤penCode锛歚~/.config/opencode/skills/uo-init` 鈫?`~/.config/opencode/skills/understand-operator`锛?2. `THIS_SKILL/../../skills/understand-operator`  
   锛堟簮鐮佹爲锛歚.../understand-operator-plugin/skills/uo-init` 鈫?`.../skills/understand-operator`锛?3. 鑻?`THIS_SKILL` 鏈韩灏辨槸 `understand-operator` skill锛歚THIS_SKILL`

PowerShell 涓€琛屾牎楠岋紙**鍙煡杩欏嚑澶勶紝绂佹 Recurse 鍏ㄧ洏**锛夛細

```powershell
$skill = "<THIS_SKILL 缁濆璺緞>"   # 鍚?SKILL.md 鐨勭洰褰?$candidates = @(
  (Join-Path $skill "..\understand-operator"),
  (Join-Path $skill "..\..\skills\understand-operator"),
  $skill
) | ForEach-Object { (Resolve-Path $_ -ErrorAction SilentlyContinue).Path }
foreach ($d in $candidates) {
  if ($d -and (Test-Path (Join-Path $d "prepare_operator.py"))) {
    Write-Host "SCRIPT_DIR=$d"
    break
  }
}
```

OpenCode 宸叉纭畨瑁呮椂锛岄€氬父鐩存帴鏄細

```text
C:\Users\<you>\.config\opencode\skills\understand-operator\prepare_operator.py
```

### 2) PLUGIN_ROOT / PROMPT_DIR

鎸夐『搴忚瘯锛?*绗竴涓瓨鍦?`prompts/common/02_cbm_first_rules.md` 鐨勭洰褰?*鍗充负 `PLUGIN_ROOT`锛?
1. `~/.config/opencode/understand-operator-plugin`锛圤penCode 瀹夎鍚?plugin junction锛?2. `~/.cursor/understand-operator-plugin`锛圕ursor skills 瀹夎鍚庯級
3. `~/.agents/understand-operator-plugin`锛圕odex 瀹夎鍚庯級
4. `SCRIPT_DIR/../..` 鑻ュ瓨鍦?`prompts/common/02_cbm_first_rules.md`锛堟簮鐮佹爲锛歚understand-operator-plugin`锛?5. 鍚﹀垯 `THIS_SKILL/../..`锛堟簮鐮佹爲 `skills/uo-init` 鐨勪笂涓ょ骇锛?
`PROMPT_DIR` = `$PLUGIN_ROOT/prompts`

### 3) PROJECT_ROOT

鐢ㄦ埛鍙傛暟璺緞锛屾垨鍚?`op_host/` / `op_kernel/` 鐨勭畻瀛愪粨搴撴牴銆? 
**涓嶆槸** `~/.config/opencode`锛?*涓嶆槸** understand-operator 鎻掍欢鐩綍銆?
### 4) UO_ROOT

`$PROJECT_ROOT/.understand-operator/$OP_NAME`

## 鎵句笉鍒版椂鎬庝箞鍔?
1. 鍙鏌ヤ笂闈?3 涓?candidate锛屾墦鍗板畠浠槸鍚﹀瓨鍦? 
2. 鎻愮ず鐢ㄦ埛鍦?understand-operator 浠撳簱鏍规墽琛岋細`./install.ps1 opencode`  
3. **鍋滄**锛屼笉瑕?`Get-ChildItem C:\ -Recurse`

## 瀹夎鍚庡簲鏈夌殑甯冨眬

```text
~/.config/opencode/
  opencode.json            # permission.question: "allow"锛坔uman review 鎸夐挳 UI锛?  understand-operator-plugin/   鈫?junction 鈫?.../understand-operator-plugin
    prompts/00_review_menu.md
    prompts/01a_macro_scope_human_review.md
    agents/uo-*.md
  skills/
    uo-init/                 鈫?junction 鈫?.../skills/uo-init
    uo-query/
    uo-update/
    uo-diff/
    understand-operator/     鈫?junction 鈫?.../skills/understand-operator
      prepare_operator.py
      quality_gate.py
      review_checkpoint.py
      verify_subagent_barrier.py
      update_operator.py
```

