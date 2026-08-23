Isolated AXIS=bind eval. Do not call pilot_run. Do not /tg-init /tg-plan /tg-solve. Do not abort any other run.

Follow the session method. One no-arg `uo-query` is required (do not skip it because a name-index exists). Write `parts/bind.fill.yaml` once. Do not Edit `parts/bind.yaml`. Then inspect yaml on bind.yaml (it merges the fill).

You are not finished until `inspect yaml` prints `"ok": true`. Do not stop after reading files.

If the plugin tool `pilot_cli` is not in this agent, use PowerShell (no --help):
  $env:PYTHONPATH = "D:\TEST\AscendC-Pilot\pilot;D:\TEST\AscendC-Pilot\engines\understand-operator\src;D:\TEST\AscendC-Pilot\engines\testcase-generation"
  Set-Location D:\TEST\AscendC-Pilot\pilot
  python -m ascendc_pilot uo-query --project "D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad" --architecture arch35
  python -m ascendc_pilot inspect yaml --project "D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad" --rel "arch35/runs/RUN_20260822_160048_c23c9341/actions/bind_init/parts/bind.yaml"

-----STUB-----
action_id=bind_init
actor_id=tg-analyst
run_id=RUN_20260822_160048_c23c9341
Follow ONLY these session files (read them first; do not invent extra goals):
  prompt: D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260822_160048_c23c9341/actions/bind_init/prompt_bind.md
  method: D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260822_160048_c23c9341/actions/bind_init/method_bind.md
  bundle: D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260822_160048_c23c9341/actions/bind_init/bundle.yaml
session_dir: D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260822_160048_c23c9341/actions/bind_init
pilot_cli commands must pass --project D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad (Host cwd is the Pilot checkout; always this absolute operator path, not the op name alone)
write: D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260822_160048_c23c9341/actions/bind_init/parts/bind.fill.yaml
forbid_read: runs/RUN_20260822_160048_c23c9341/actions/bind_init/parts/harness.yaml
environment: D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260822_160048_c23c9341/actions/bind_init/environment_capabilities.yaml
USER QUESTION (answer this against the CodeMap / minimal source windows):
AXIS=bind
FOCUS: parts/bind.yaml（call / mapping / domains）
SLICE_ID=bind
Read only the method path in this stub. Write only `parts/bind.fill.yaml`. Do not Edit `parts/bind.yaml`. Do not Write the other axis or canonical products. Do not Read runs/RUN_20260822_160048_c23c9341/actions/bind_init/parts/harness.yaml.
Hard stop: this Task answers ONLY the FOCUS / SLICE_ID above. Ignore other parts of prompt.md User question.
Return a short summary when done.
Do NOT finalize; Host `pilot_run` holds finalize for `bind_init`.
-----END STUB-----
