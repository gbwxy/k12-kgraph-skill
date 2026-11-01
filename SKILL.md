---
name: k12-kgraph-skill
description: 在本地 Agent 中使用 K12-KGraph（北京大学 NeurIPS 2026 教育知识图谱：人教版 K1–K12 数学/物理/化学/生物，10,685 节点 / 23,278 边）。查询概念定义与重要程度、先修关系链、教材出处、关联实验与习题，生成课程锚定的学习路径、薄弱点根因诊断、教学问答与练习题，或运行 K12-Bench 评测。当用户提到 K12-KGraph、K12 知识图谱、知识点图谱、先修知识/前置知识/prerequisite、学习路径、薄弱点回溯/根因诊断、人教版知识点、教材出处查询、课程锚定出题或 QA 生成时使用本技能——即使用户没有点名数据集。
---

# K12-KGraph 本地使用

K12-KGraph 是北京大学 PKU-DCAI 团队发布的课标知识图谱（NeurIPS 2026 Evaluations & Datasets Track）：基于人教版 48 本教材抽取，含 7 类节点（Book / Chapter / Section / Concept / Skill / Experiment / Exercise）和 9 类关系，配套 K12-Bench（23,640 道多选题）与 K12-Train（2,267 条 QA）。

**许可红线**：数据 CC BY-NC-SA 4.0（**禁止商用**，衍生需同许可），上游仓库代码 MIT；本 skill 与其一致——文档 CC BY-NC-SA 4.0、代码 MIT（见 LICENSE / LICENSE-CODE）。对外产品化前必须确认授权；向用户输出数据时注明来源。

**本技能目录**：`scripts/kg.py`（纯 stdlib 查询 CLI）、`scripts/fetch_data.sh`（数据下载）、`references/schema.md`（完整 schema 与 ID 规范）。

## 0. 快速决策

| 用户想要 | 做法 |
|---|---|
| 查几个知识点 / 看数据长什么样 | 不下载全量：`git clone https://github.com/haolpku/K12-KGraph` 后用 `demo/kg/math_7a_rjb.json`（七年级上数学，157 节点 / 285 边）跑 kg.py |
| 完整图谱查询、学习路径、诊断 | `scripts/fetch_data.sh core` 下载到 `~/.cache/k12-kgraph/`，然后 kg.py |
| 更新缓存（数据过期 / 上游修复后） | `scripts/fetch_data.sh update` 刷新已缓存文件（条件请求只拉变更，自动补缺失文件） |
| 跑模型评测 | K12-Bench + 仓库 `eval/run.sh`（需要 API key 或 vLLM/GPU，见 §5-D） |

## 1. 获取数据

```bash
# 核心图谱（global_KG + 4 个学科图，约 13 MB）——日常查询用这个
bash scripts/fetch_data.sh core

# 全量（再加 15 册课后习题 + K12-Bench + K12-Train，约 25 MB）
bash scripts/fetch_data.sh all

# 更新缓存：上游数据变更后运行（只拉变更 + 自动补缺失的 core 文件）
bash scripts/fetch_data.sh update
```

脚本默认走 `https://hf-mirror.com`（国内可达）；海外或想走官方源时 `HF_ENDPOINT=https://huggingface.co bash scripts/fetch_data.sh core`。下载位置默认 `~/.cache/k12-kgraph/`（可用环境变量 `K12KGRAPH_DATA` 覆盖）。

等价的手工方式：

```python
from datasets import load_dataset
kg    = load_dataset("lhpku20010120/K12-KGraph", split="train")            # 图谱
bench = load_dataset("lhpku20010120/K12-KGraph", name="bench",  split="test")  # 评测
train = load_dataset("lhpku20010120/K12-KGraph", name="train",  split="train") # SFT
```

## 2. 数据文件布局

```
~/.cache/k12-kgraph/
├── K12-KGraph/
│   ├── global_KG/nodes.json + edges.json     # 全局图谱（属性精简）
│   ├── subject_specific_KG/{math,physics,chemistry,biology}.json  # 学科图谱（属性丰富，优先用）
│   └── afterclass_exercises/*.json           # 15 册课后习题（math 8 册 + chem 7 册）
├── K12-Bench/*.jsonl                         # 9 个任务文件（ground/prereq/neighbor/evidence/locate）
└── K12-Train/train.jsonl                     # 2,267 条 KG 锚定 QA
```

kg.py 会自动递归合并目录下所有含 `nodes`/`edges` 的 JSON（学科图属性覆盖全局图），无需手工挑选文件。

## 3. Schema 速查（详见 references/schema.md）

**节点**：`{id, label, name, properties{…}}`，`label` ∈ Book / Chapter / Section / Concept / Skill / Experiment / Exercise。常用属性：Concept 有 `definition / importance(了解|掌握|重要) / formula / aliases / examples`；Exercise 有 `stem / answer / difficulty(1-5) / analysis`；Experiment 有 `instrument / is_student / process / phenomena / conclusion`。

**边**：`{source, source_name, target, target_name, type, properties{evidence…}}`，`type` ∈
`prerequisites_for`（source 是 target 的先修）、`is_a`、`relates_to`、`verifies`（实验→概念）、`tests_concept` / `tests_skill`（习题→概念/技能）、`appears_in`（知识→教材位置）、`is_part_of`、`leads_to`。

**ID 规范**：`{subject}_{册码}_rjb_{类型码}{序号}`，如 `math_7a_rjb_cpt17`（数学七上·人教版·概念17）。类型码 `cpt/skl/exp/exe`；章节 `math_7a_rjb_ch2`、`math_7a_rjb_ch2_s3`。册码：小学 `1a–6b`、初中 `7a–9b`、高中必修 `bx1–bx3`、选择性必修 `xzxbx1–xzxbx3`。

## 4. 查询工具 kg.py

```bash
python3 scripts/kg.py --data ~/.cache/k12-kgraph stats          # 规模统计
python3 scripts/kg.py --data ~/.cache/k12-kgraph find 倒数      # 按名称/别名搜索
python3 scripts/kg.py --data ~/.cache/k12-kgraph show math_7a_rjb_cpt24   # 节点详情+关系
python3 scripts/kg.py --data ~/.cache/k12-kgraph prereq math_7a_rjb_cpt26 # 先修链+学习顺序
python3 scripts/kg.py --data ~/.cache/k12-kgraph path math_7a_rjb_cpt24 math_7a_rjb_cpt26
python3 scripts/kg.py --data ~/.cache/k12-kgraph locate math_7a_rjb_cpt24 # 教材出处
python3 scripts/kg.py --data ~/.cache/k12-kgraph exercises math_7a_rjb_cpt24  # 考察该点的习题
python3 scripts/kg.py --data ~/.cache/k12-kgraph neighbors math_7a_rjb_cpt24 # is_a/relates_to 邻居
python3 scripts/kg.py --data ~/.cache/k12-kgraph check-cycles   # 环检测（见 §6）
```

- 未指定 `--data` 时依次找 `$K12KGRAPH_DATA`、`~/.cache/k12-kgraph`，也可以直接 `--data demo/kg/math_7a_rjb.json` 指到单个文件。
- 输出为稳定的英文键 + 原始中文数据，方便直接改写成给用户看的 Markdown 表格。
- `find` 找不到就先跑 `stats` 确认数据已加载；中文关键词用全名或核心词（"倒数"而不是"求倒数的方法"）。

## 5. 常见任务工作流

### A. 知识点查询 / 备课素材

1. `find <关键词>` 拿到 id；拿不准就多试几个词（别名在 `properties.aliases`）。
2. `show <id>` 看定义、重要程度、公式。
3. `locate <id>` 给出教材册/章/节出处（appears_in 链），用于标注"人教版 X 年级上册 第 Y 章"。
4. `exercises <id>` 拉出考察该点的课后习题（stem / answer / difficulty），用于选例题。

### B. 学习路径 / 薄弱点根因诊断

1. 对学生卡住的知识点跑 `prereq <id> --transitive`，得到全部先修集合。
2. 脚本输出的 `topo_order` 就是建议的补学顺序（先修在前）。
3. 根因诊断：从出错点沿先修边**逆流而上**，对每个先修用 `exercises` 挑 1 道低难度题验证；第一个答错的点即根因（参考做法：每点最多 2 题，连续答对可跳过更远祖先）。
4. 向用户输出路径表：

```markdown
| 顺序 | 知识点 | 重要程度 | 教材出处 | 建议练习 |
|---|---|---|---|---|
| 1 | 倒数(math_7a_rjb_cpt24) | 掌握 | 七上 第2章 | exe3, exe7 |
```

### C. 课程锚定 QA / 出题

1. 用 `show` 的节点属性（definition/formula/examples）+ `prereq`/`neighbors` 的关系做上下文。
2. 生成问答时锚定字段：概念题看 `definition`，关系题看边的 `properties.evidence`（教材原文证据），习题改编看 `stem/analysis`。
3. 批量生成参照仓库 `src/sft_qa/prompts/`（concept / is_a / prerequisites_for / relates_to / skill / verifies 六类模板）。
4. 生成的题目标注"AI 生成，需教师审校"。

### D. K12-Bench 评测模型（进阶，非查询场景）

1. `bash scripts/fetch_data.sh all` 取 K12-Bench（9 个 jsonl，一行一道多选题）。
2. 评测走仓库 `eval/run.sh` + `eval/configs/models/*.yaml`（16 个模型配置，含 API 与 vLLM 两类）；对照零样本基线：Gemini-3-Flash 57.1 EM / 73.0 F1 为已报告最高。
3. 只改提示词或轻量实验：直接读 jsonl 自己组 prompt 即可，不必跑完整 eval 管线。

## 6. 坑与注意事项

1. **先修图存在环（issue #8）**：官方发布的 `is_a` 与 `prerequisites_for` 子图被实证存在环（2026-10-19 提出，未修复）。做拓扑排序、学习路径前先跑 `check-cycles`；脚本的 topo_order 会自动破环并警告。别把"无环"当事实。上游修复后运行 `bash scripts/fetch_data.sh update` 刷新缓存，再用 `check-cycles` 复验。
2. **数学没有 Experiment 节点**（物理/化学/生物才有），数学的 `verifies` 相关问题无数据。
3. **global_KG 属性精简、学科图属性丰富**：定义、公式等只在 `subject_specific_KG/*.json` 里完整；kg.py 合并后自动取丰富的，手工读文件时注意选学科图。
4. **bench 是多选题**（EM/F1 口径），做能力评估时注意题型局限。
5. **许可 NC**：数据禁止商用；给用户的输出注明"数据来源 K12-KGraph（CC BY-NC-SA 4.0）"。
6. 只有人教版（rjb）教材；北师大/苏教版不在覆盖内。
7. 数据是 LLM 辅助抽取 + 专家评审（κ=0.84），高风险场景（如直接影响升学的诊断结论）人工复核。

## 7. 相关链接

- 仓库：https://github.com/haolpku/K12-KGraph ｜ 数据集：https://huggingface.co/datasets/lhpku20010120/K12-KGraph
- 论文：https://huggingface.co/papers/2605.09635 ｜ 项目主页：https://haolpku.github.io/K12-KGraph-page/
- 三项目对比调研（同工作区）：`doc/k12/07-知识图谱三项目对比.md`
