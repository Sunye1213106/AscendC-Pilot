# Human Review UX 鈥?selectable UI (Plan-style)

寮哄埗浜哄伐瀹￠槄闂搁棬锛?*Phase 0.5 / 3.5**锛堜互鍙?uo-query 缂?KB锛夈€?
**鍙湁杩欎簺闂搁棬**鎵嶅厑璁革細鏆傚仠锛圫TOP锛? 鍦ㄥ璇濋噷闄勪笂鍙緵浜哄垽鏂殑瀹￠槄鎽樿銆? 
鏅€?phase锛堝惈 Phase 1 瀹忚杈圭晫瀹屾垚鍚庯級**绂佹**杈撳嚭瀹￠槄寮忔憳瑕佹垨鍋囪绛変汉銆?
鐩爣浜や簰涓?Cursor Plan / OpenCode `question` 涓€鑷达細

- **鈫?鈫?鎴栫偣鍑婚€夋嫨**鍥哄畾閫夐」
- **鏈€鍚庝竴椤规敮鎸佽嚜鐢辫緭鍏?*锛堟墜宸ヨˉ鍏咃級
- 閫夊畬鍚?agent 鐢?`--decision` 钀界洏锛屽啀缁х画

**绂佹**鍐嶇敤浼氭姠 stdin 鐨?Python raw 閿洏寮圭獥锛坄--arrows` / 闃诲 `input()`锛夈€傞偅浼氳鑱婂ぉ妗嗘棤娉曟墦瀛椼€?
## 浼樺厛锛氬師鐢熼€夋嫨 UI

### OpenCode

浣跨敤鍐呯疆 **`question`** 宸ュ叿锛坧ermission 闇€ allow锛夈€傜敤鎴峰彲锛?
- 鐢ㄩ敭鐩?榧犳爣閫夊浐瀹氶€夐」
- 鎴栬緭鍏?custom answer锛堝搴旀墜宸ヨˉ鍏咃級

绀轰緥闂缁撴瀯锛?
```text
header: Phase 0.5 Macro Scope
question: 璇风‘璁?Phase 1 鎺㈢储鑼冨洿鍚庡浣曠户缁紵
options:
  - continue 鈥?鎸夊綋鍓嶈寖鍥磋繘鍏?Phase 1
  - revise 鈥?璋冩暣 include/exclude/skip 鍚庨噸瀹?  - stop 鈥?鍋滄 workflow
  - manual_supplement 鈥?鎵嬪伐琛ュ厖锛堥€夋椤瑰悗璇疯緭鍏ヨˉ鍏呭唴瀹癸級
```

鑻ョ敤鎴烽€変簡 `manual_supplement` 鎴栨彁浜や簡 custom text锛氭妸鏂囨湰褰撲綔 `notes`銆?
### Cursor

鑻ョ幆澧冩彁渚?**AskQuestion**锛堟垨鍚岀瓑閫夋嫨 UI锛夛細

- 鍗曢€夊浐瀹氶€夐」
- 鏈€鍚庝竴椤瑰繀椤绘槸锛歚鎵嬪伐琛ュ厖锛堟垜鏉ヨ緭鍏ワ級` / `Something else (I will type it)`
- 涓嶈鍦ㄥ悓涓€棰樺啀鏀惧彟涓€涓?鈥淥ther鈥?
鑻?AskQuestion 涓嶅彲鐢細鍦ㄨ亰澶╅噷缁欏嚭鍚屾牱閫夐」锛屽苟鏄庣‘鍐欍€岃鍥炲閫夐」鍚嶏紱閫夋墜宸ヨˉ鍏呮椂鍦ㄥ悓涓€鏉℃秷鎭啓鍐呭銆嶃€?
## 钀界洏锛堜袱绉?UI 閫夊畬鍚庨兘瑕佸仛锛?
```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate <gate> --decision <choice> [--notes "..."] [--approved-task-ids "..."]
```

`<gate>`锛?
| Phase | `--gate` |
|---|---|
| 0.5 Macro Scope | `macro_scope` |
| 3.5 Kernel Dispatch | `kernel_dispatch` |
| uo-query 鎵句笉鍒?KB | `query_missing_kb` |

鍙€夛細鍏堟墦鍗拌彍鍗曞蹇橈紙涓嶉樆濉烇級锛?
```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate <gate>
```

## 鍚勯椄闂ㄩ€夐」锛堟渶鍚庝竴椤?= 鍙緭鍏ワ級

### macro_scope

1. `continue`
2. `revise`
3. `stop`
4. `manual_supplement` 鈫?**鏀寔杈撳叆**锛堣寖鍥?璺宠繃鍒嗘敮绛夛級

### kernel_dispatch

1. `dispatch_all`
2. `dispatch_subset` 鈫?閫夊悗闇€鎻愪緵 task_id锛堝彲鍦?custom 杈撳叆閲屽啓锛?3. `revise`
4. `stop`
5. `manual_supplement` 鈫?**鏀寔杈撳叆**

### query_missing_kb

1. `init`
2. `source`
3. `stop`
4. `manual_supplement` 鈫?**鏀寔杈撳叆**锛圞B 璺緞 / op-name锛?
## Agent 姝ラ锛堝繀椤伙級

1. **浠呭湪闂搁棬 turn**锛氬睍绀哄闃呮憳瑕侊紙3.5 蹇呴』鍚叏閲?tiling/family锛?2. 璋冪敤鍘熺敓 `question` / AskQuestion锛堟渶鍚庝竴椤瑰彲杈撳叆锛?3. **STOP** 绛夊緟 UI 杩斿洖
4. `--decision` 鍐欏叆 `*_decision.json` / review yaml
5. 鎸夊喅绛栫户缁紱`manual_supplement` / `revise` 鍚告敹 notes 鍚庡彲鍐嶆鎻愰棶

## 绂佹

- 绂佹鍦ㄩ潪闂搁棬 phase锛堝挨鍏?Phase 1 缁撴潫鍚庯級鍚戝璇濊緭鍑?Boundary/IO/open_questions 绛夈€岀粰浜虹湅鐨勫闃呮潗鏂欍€?- 绂佹 Python `--arrows` / `--interactive` 浣滀负 OpenCode/Cursor 榛樿璺緞
- 绂佹鏇跨敤鎴烽粯璁?`continue`
- 绂佹鍙创闈欐€佸垪琛ㄥ嵈涓嶅敜璧峰彲閫夋嫨 UI锛堟湁 `question`/AskQuestion 鏃讹級
- 绂佹鍦ㄦ湭鑾峰緱鏄庣‘ `continue` 鏃惰繘鍏ヤ笅涓€闃舵

