# 融合医学临床教学案系统

把"西医诊断 + 检验指标 + 中医证候 + 十几种药物并排抄一页"的教学查房记录，替换为
**分层、带来路、可比较、守边界**的事件溯源系统。系统只做记录与来路的守门，
**不替师生裁定哪种医学体系优先，也不把相关性包装成疗效**。

## 分层模型（四个事件流）

| 聚合 | 内容 | 主要事件 |
| --- | --- | --- |
| `teaching_case` | 脱敏病例、教学同意、授权期限、撤回/到期 | `CASE_RELEASED` `CONSENT_WITHDRAWN` `ACCESS_EXPIRED` |
| `clinical_observation` | 症状/检查事实、舌脉证候（须引用事实）、冲突、相互作用旗标、候选机制 | `OBSERVATION_ADDED` `OBSERVATION_CORRECTED` `CONFLICT_IDENTIFIED` `INTERACTION_FLAGGED` `MECHANISM_PROPOSED` |
| `student_plan` | 问题表述（须引用观察）、各版方案与治疗取舍 | `PROBLEM_FORMULATED` `PLAN_SUBMITTED` |
| `faculty_feedback` | 跨学科分歧（并存）、模拟、临床回顾、能力证据 | `OPINION_RECORDED` `OPINION_CORRECTED` `SIMULATION_RECORDED` `CASE_REVIEWED` `COMPETENCY_EVALUATED` |

事件不可变；更正只能追加 `*_CORRECTED`，投影保留完整历史。同一聚合 `version` 从 1
连续递增，`event_id` 全局唯一，来源系统重试沿用原标识（相同内容幂等，不同内容拒绝）。

## 关键教学规则（在提交时强制）

- **每次取舍必须说明依据**：每项治疗为 `merged / retained / excluded / deferred` 之一，
  附 rationale、针对的问题和证据来路；排除还要选分类（禁忌/重复/证据不足/相互作用…）。
- **合并必须真跨体系**：`merged` 要列出被合并的至少两项、分属不同体系，且能在上一版
  找到来路；同体系删减记成排除。悄悄删药在修订视图中标红。
- **重复用药必须确认**：多个保留/合并的治疗含同名成分时，须逐条在
  `duplication_acknowledgments` 说明是否有意、是否减量。
- **高危相互作用必须有处置**：保留成分命中 high/contraindicated 旗标时，须给出
  rationale 与 resolution（调整/监测/停用）。
- **相关性 ≠ 疗效**：候选机制分 `correlation / hypothesis / validated_outcome` 三档，
  最后一档必须引用干预性研究；单病例随访只能记 `individual_followup`；
  相互作用旗标禁止携带疗效断言。
- **教师分歧并存**：支持/担忧/反对/替代以 `supports/disputes/extends` 串联，教师只能
  更正本人意见，不能覆盖他人意见。
- **证候不悬空**：pattern 类证候观察必须引用支持它的事实。

## 授权生命周期

- 发布时同时登记**脱敏核验**（直接标识全部移除、研究代号、审核人）、**教学同意书**
  （依据、范围文本）与**授权课程清单和起止时间**。
- 授权到期或同意撤回后，课程系统立即**停止新课程访问**（墓碑事件优先广播）。
- 已形成的**成绩证据按保留规则**处置：`retain_full / retain_anonymized / delete_evidence`；
  匿名保留时切断与可识别学生的关联，只留稳定派生的学号假名，评分维度与证据来路不丢。

## 方案修订并排视图

`src/revision.py` 对任一方案版本同屏呈现四栏来路：

1. **新增事实**（本版窗口内新增的事实与证候，带来源事件）
2. **冲突识别**（含跨体系冲突是否仍开放）
3. **治疗取舍**（与上一版逐条 diff、依据、合并来源、排除理由、重复/相互作用确认）
4. **教师分歧**（哪些意见被本版取舍直接引用、哪些反对仍未回应）

并给出只描述结构、不替教师打分的整合度指标：跨体系合并数、共同解释两套体系问题的
机制数、有依据排除数、拼贴风险信号（"全部并列保留、没有任何合并""未说明的悄悄删药"
"跨体系冲突未解释"），让课程负责人用**真实决策变化**判断教学是否仍只是拼术语。

## 跨课程同步（`src/sync.py`）

- 按 `teaching_case / clinical_observation / student_plan / faculty_feedback` 四层通道同步；
- 病例事件只投递给同意范围内的课程；撤回/到期墓碑广播给所有持有副本的课程；
- 成绩证据默认**不外发**（显式 `allow_grade_export` 才跨课程）；
- 接收侧拒绝没有发布事件在前的孤立同步；重复投递幂等。

## 目录

- `contracts/domain.schema.json`：事件信封契约（枚举已扩展到全部 15 个事件）。
- `src/events.py`：事件类型归属与全部载荷的结构化中文校验。
- `src/store.py`：只追加事件存储（幂等、版本连续、JSONL 导入导出）。
- `src/projections.py`：只读投影（授权状态、各层当前态、更正历史、成绩证据视图）。
- `src/system.py`：领域服务（写入矩阵、授权守卫、引用完整性、重复/相互作用确认）。
- `src/revision.py`：修订并排视图（结构化数据 + Markdown 渲染）。
- `src/sync.py`：课程间事件总线。
- `src/scenario.py`：一个完整中文教学案（拼贴 v1 被守卫两次拦下 → 教师分歧并存 →
  整合 v2 → 模拟/回顾/能力评价 → 到期匿名保留）。
- `tests/`：34 个测试，覆盖契约、守卫、修订视图、同步幂等与墓碑。

## 运行

```bash
python3 -m unittest discover -s tests   # 测试
python3 -m src.demo                     # 中文端到端走查（含两版修订并排报告）
```
