# RED baseline — bind-init columns (ses_fd64 / subagent_d4)

Baseline = real bind slice, not a fresh run. Skill at snapshot: `skill-snapshot/`.

Pressures: 41 CSV columns, identifier budget ≤8, 14 min already spent, Write-vs-Edit on 869-line YAML.

## Verbatim rationalizations

1. Empty `uo_id` as PARTIAL — "I'll set uo_id: '' … The method explicitly allows this: 查不到 → PARTIAL"

2. Shape dim bound to computed kwarg — "具名实参赢" → D 绑 scaleValue

3. Feature left empty despite header field — inner_drop 不填 dropMaskOuter

4. Homemade `scratch/check_bind.py`；skill 当时没写 inspect yaml

5. Speed — 通读 runner；打满 8 次标识符查询；Write 整文件

6. eod → api_arg — "eod modifies B and seqlens which feed the call"

7. domains — operator 空仍 compare: match；seqlens operator: Dim=IsTnd

## Form chosen

| Failure | Form |
| --- | --- |
| empty uo_id / budget PARTIAL | slot: 短名进 uo_id；PARTIAL 只进 findings |
| 具名实参赢 on computed kwarg | 当且仅当该列是 kwargs 的 source_column |
| feature omit header field | 头文件有开关就填 uo_id |
| scratch checker | 循环最后一步 inspect yaml |
| reread / 8 queries | 头文件一次抄完再补洞 |
| eod as api_arg | 裁切列 = feature |
| empty operator + match / Dim=IsTnd | operator 非空才 match；序列列绑 proto 短名 |
