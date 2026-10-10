# T3 公开比赛诊断修复 r2：源代码审查结论

## 结论

**有条件可冻结。** 在给出的代码范围内，没有发现 r2 引入的实质阻断。driver 谓词修复、auditor 绑定块和 source preflight 三者逻辑一致，源绑定没有出现可被绕过的缺口。

但还有几处下游代码不在本次提交范围内。若其中任何一处仍按旧 driver SHA 绑定，r2 在 Linux 上会**确定性失败**。因此冻结前必须完成下面 3 项 grep 确认（见第三节）。

## 一、逐项审查

### 1. driver.py：`normalize_unit`

- 新谓词 `len(item['subs']) >= 1` 正确，空 batch 仍被拒绝。
- 6/8 场景 batch 的完整性仍受原有约束保护：
  - `scenario_paths` 数量必须等于 `subs` 数量；
  - `reference_frames` 数量必须是 `subs` 的 2 倍；
  - sub 映射必须精确，sub 名不能重复；
  - SHA 字段必须是 64 位十六进制。
- `roster` 的三重比较（saved / prior / current）与逐文件 SHA 复算均未改动。
- 第二道闸门同样未改动：所选 6 个 unit 必须恰好是 10 个 market，且最后一个 unit 恰好 5 个 sub。这道闸门保证 worker、parser、overlay 的 `<=5` 上限只约束所选范围，结论成立，无需扩大这些上限。

**既有问题（非 r2 回归，不阻断）：**

- `normalize_unit` 的返回值不包含 `scenario_paths` 和 `reference_frames`，所以跨计划比较只比数量、不比内容。
- 这两个字段的 list 类型也未检查。
- 内容层面由 `input_sha256`/`reference_sha256` 两个映射和逐文件复算兜底，而 worker 实际使用的是 `current` 这份实测计划。按"最小修复"原则，本轮不建议改动。

### 2. auditor：`source()` 绑定块

- 执行顺序正确：
  1. 先校验 review 的完整字节 SHA `780a…`；
  2. 再用旧 review 的 bytes/sha 校验 `driver_before_batch_repair_r1.py`；
  3. 然后检查旧谓词恰好出现 1 次，且新 driver 的字节完全等于"旧字节仅替换该谓词"的结果。
- 这里是全文件字节相等，不是子串匹配，所以其他任何字节变动都会被拒绝。
- worker 和 parser 仍绑定原 review，parser 还额外与 REFERENCE 副本比对。
- 旧 driver 副本同时受到两层约束：`inventory(carried) == pins['files']`，以及 remote samehead 检查。它不可能被单独替换。
- 没有伪造新 review，旧 review 与 r1 均未改动，符合声明。

### 3. source_preflight_batch_r2.py

- 用例数核对：2 + 1 + 71 + 1 + 7 + 2 + 2 + 1 + 4 + 1 = 92，与声明一致。
- 执行的是 auditor 的真实 AST 片段（从 `original_driver` 到 `remote` 之前），绑定的确实是生产代码，而非复制品。
- 旧代码的误拒绝能被复现。原因是：只有被替换的谓词导致失败；若是 NameError 等其他错误，异常未被捕获，脚本会直接崩溃，不会被误记为 PASS。

## 二、可选的最小补强（只改 preflight，不改 driver/auditor）

1. **补 review 完整字节校验。** preflight 读取 `INDEPENDENT_HOST_SOURCE_REVIEW_v1.json` 时没有校验其 SHA（auditor 在绑定块外部校验）。建议增加：
   `check('review_pin', lambda: require(driver.pin(HERE/'INDEPENDENT_HOST_SOURCE_REVIEW_v1.json')['sha256']=='780aa8fa…a7'))`
2. **补两个"等长或语义级"反例**，证明拒绝不依赖于追加字节：
   - carried `driver.py` 写回旧字节（未修复版）→ 应拒绝；
   - 新 driver 中把 `>= 1` 改为 `>= 0` → 应拒绝。

以上两项不加也不构成阻断。

## 三、冻结前必须确认的下游阻断风险

以下文件不在本次提交中，需逐一 grep 确认：

1. **driver 旧 SHA / 字节数是否被其他地方引用。** 检查 `read_only/host/verify_linux.py`、`verify_public.py`、workflow 源码、`overlay/IMAGE_BINDING.json` 以及 HOST_AUTHORITY 的生成逻辑中，是否出现 `c9fb7fa7…` 或 `46282`，或是否用 `reviewed['source_files']['driver.py']` 直接校验 `driver.py`。
   - 若有，r2 必然失败。
   - 若在 17 个只读文件或 `IMAGE_BINDING` 中，修改它会连带破坏固定 SHA `f05b…`，或改变 binding 本身。这就超出了"唯一谓词"的范围，需要另行评估。
2. **修改后的 auditor 是否被其他固定 SHA 引用。** 确认 `audit_cost_saved_v1.py` 不在 `READ_ONLY_SOURCE_PINS_v1.json` 的 17 个文件或 `REFERENCE_SHA` 中，而是只由新的 `SOURCE_PINS` 绑定。否则 `all17unchanged…` 或 helper 检查会失败。
3. **driver 是否只把 `UNITS` 中的 unit 交给 worker、parser 和 overlay。** 确认没有任何路径会把 71 个 unit 中的 6 或 8 场景 batch 送入 worker（`scenario_paths<=5`）、parser（`roster<=5`）或 overlay（`<=5`）。
   - 若存在，本次失败只会从 driver 前移到 worker，重演 r1。

## 四、最终判断

- 若上述 3 项确认均无命中：**可冻结**（上方两条 preflight 补强为可选）。之后生成完整的新 pins，完成 remote samehead readback，再 dispatch。
- 不涉及 Linux 或性能 PASS 的判断。r1 的 artifact 下载与本结论无关。
