# Agent 材料版本与核对接口

适用版本：v0.73.11 公开预览版；仅本机服务。本说明对应现有接口，不授权绕过用户选择或直接修改数据库。物理含义见 [材料输入说明](MATERIAL_INPUTS.md)。

## 访问与版本规则

从当前服务 `GET /api/bootstrap` 取得版本、方案列表、`material_support` 和本次服务的 token。POST 使用 JSON、`Content-Type: application/json`、`X-Workbench-Token: <token>`；浏览器调用保持同源。重启后重新读取 token，不保存到公开文件。

`GET /api/material-library` 取得模板、库版本及能力说明；`GET /api/components/material` 读取已保存材料版本。组件引用使用返回的 `id`、`revision`、`sha256`，不能用名称定位唯一版本。方案请求使用该方案已保存的版本号，冲突时重新读取并核对，不强制覆盖。

## 统一登记与能力判断

`GET /api/material-library` 增加 `registration`：`modes` 描述三种计算方式，`models` 将已有模型映射为 optical/storage/resistance，`resistance_template` 提供不带 ECA 数值的等效热阻模板。界面说明不会改变原定义结构。

- optical：`optical_surface_v1`，仅改变覆盖后表面光学。
- storage：`solid_layer_v1` 或 `solid_variable_v1`，完整物性，当前通用入口仍只支持各状态固定计算。
- resistance：`equivalent_resistance_no_layer_storage`，沿用两态 A/B 等效热阻结构和已有建筑适配限制。不能添加仅为新模型定义的 category、property_source、solar_input、visible_absorptance 等字段。

材料形态、用途与来源填写在已有 `source_note` 中。状态名与形态不决定计算方式，两个状态也不意味着动态控制已开放。保存独立材料版本不改变任何方案。将已有材料改为另一种模型或状态数量，应复制为新材料并展示参数保留、缺失和移除情况，核对后再保存；不得静默改写旧身份。

采用预览会拒绝将不计新增层蓄热的材料选入热学 feedback 方案，提示先另存并明确改为固定状态。计入蓄热的新模型继续受原 fixed-only 适配限制；不能绕过它。该拦截针对新选用，不删除或改写已有 Drawing26 历史方案、控制和结果；历史能力不是通用新版动态能力。

旧等效热阻光学继续保存 `input_basis`、`reflectance`、`solar_absorptance`、`emissivity`。切换输入表示须保持同一物理吸收率；不能因为修改发射率而重解释太阳输入。切换由厚度/导热率计算为直接热阻时，先保留当前算得的热阻。

## 新模型的光学输入

`model` 为 `optical_surface_v1`、`solid_layer_v1`、`solid_variable_v1` 时，光学仍保存规范化 `solar_absorptance`。可选依据为：

```json
{
  "input_basis": "effective_surface_absorptance",
  "solar_absorptance": 0.045,
  "solar_input": {"quantity": "reflectance", "value": 0.955},
  "emissivity": 0.9
}
```

`quantity` 只允许 `absorptance` 或 `reflectance`。依据与吸收率不一致时拒绝保存，不自动改写；旧快照没有 `solar_input` 时仍按原吸收率理解，不强制回填。仅改变表示时保留规范化吸收率，只调整输入依据；不得重新解释旧值。可见光吸收率省略或为 null 表示按目标继承，不应在材料定义中擅自补 0.7。

`optics` 的稳定键仍为 `A_R` 等；状态 ID 仍为 R/C。显示采用 `states[].name`。不随热学状态变化时仅用 A_R/B_R，显示 A/B；不能把 R/C 或名称当作高低热阻、压缩方向判断。

## 密度预览与明确采用

`POST /api/material-library/density-preview`：

```json
{
  "content": "完整的可调实体材料定义对象，此处仅示意",
  "source_state": "R",
  "cp_rule": "independent",
  "confirmed": true
}
```

实际请求中的 `content` 必须为对象。`confirmed: true` 仅在使用者已明确确认同一试件、质量和覆盖面积不变时发送。`cp_rule` 为 `independent` 或明确选择后的 `shared`。返回 `source`、`target_before`、`target_after`、两态汇总、`relationship` 和说明；接口不保存、不采用、不计算。

核对返回值及原草稿仍一致后，才将目标密度（以及 shared 时的目标比热）和 `relationship` 写入材料草稿，字段名为 `state_relationship`。不要覆盖返回中无关字段。关系记录模式、源/目标状态、比热规则及推算时输入。导热率不推算。

依赖项或派生值变化会导致保存及生成拒绝。应重新预览、再次明确采用；或由使用者选择解除关系、保留现值独立填写，并记录原推算依据。不要删除关系以绕过校验，不静默推算或覆盖手填值。

## 保存材料、采用方案、生成输入

1. `POST /api/components`，提交 `{kind:"material", name, content}` 保存新材料。追加版本时加 `parent:{id,revision}`，返回完整组件快照。保存版本不改变方案。
2. `POST /api/material-library/targets`，提交 `{id,revision,changes}` 查询当前方案可用目标。
3. `POST /api/material-library/adoption-preview`，提交 `{id,revision,changes,target:{id,revision,sha256},selection:{state_id,face,targets}}`。selection 中 targets 为已明确选定的表面 ID；审阅材料、控制变化和 audit。此接口不保存。
4. 明确采用后将返回的 `materials` 与 `controls` 写入方案草稿相应因素，再走原方案保存入口；保留其他因素、版本及结果引用。可通过页面执行此步骤，禁止直接写 SQLite。
5. `POST /api/material-library/optics-preview`，提交 `{id,revision,changes}` 核对本方案实际光学。audit 逐表面列出 `visible_absorptance.value/source/original_material/original_value`；来源分别为 `user_override`、`target_outer_layer`、`engine_default`。单层仅光学模型还列 `preserved_inside_optics`。
6. 复用平台原输入生成、预算、核对及计算提交流程，不把保存材料当作启动计算。

`changes` 为当前方案允许的修改对象；无草稿变更时用 `{}`。采用预览绑定原方案与所选组件版本，异步返回后若草稿改变应重做预览。通用新模型只接受固定状态与固定光学参数组，不能借用旧 ECA 动态控制字段。

新增元数据是可选字段，旧方案不会自动迁移。人的页面和上述接口共用材料校验、版本快照及计算适配路径。单层外侧光学修正只改变此类新生成输入；旧结果与旧 ECA 接法保留。
