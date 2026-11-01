# K12-KGraph Schema 与 ID 规范

> 来源：仓库 `src/kg/prompt.txt`（抽取规范）、`src/utils/k12_ids.py`（ID 规范）、`demo/kg/math_7a_rjb.json`（实例）、HF 数据集卡片（文件布局）。2026-11-01 核验。

## 1. 文件布局（HuggingFace `lhpku20010120/K12-KGraph`）

```
K12-KGraph/
├── global_KG/
│   ├── nodes.json        # 1.27 MB，全部 10,685 节点（属性精简）
│   └── edges.json        # 2.65 MB，全部 23,278 边
├── subject_specific_KG/  # 学科图谱，节点属性更丰富（定义/公式/例题等）
│   ├── math.json  physics.json  chemistry.json  biology.json
└── afterclass_exercises/ # 15 册课后习题
    ├── math_7a_rjb.json … math_9b_rjb.json（初中 6 册）
    ├── math_highschool_rjb_bx1.json / bx2.json
    ├── chemistry_9a_rjb.json / 9b_rjb.json
    └── chemistry_highschool_rjb_{bx1,bx2,xzxbx1,xzxbx2,xzxbx3}.json
K12-Bench/   # 9 个 jsonl，一行一道多选题，共 23,640 题
K12-Train/train.jsonl   # 2,267 条 KG 锚定 QA（SFT 用）
SFT-Baselines/          # 8 个同预算对照语料（dataflow/infinity/lmsys/openhermes/smoltalk/tulu3/ultrachat/wizardlm，各 2,300 条）
```

注意：GitHub 仓库本身**不含** data/ 目录，只有 `demo/` 样例（`demo/kg/math_7a_rjb.json` = 七上数学单册图谱，157 节点 / 285 边；`demo/benchmark/*.jsonl`、`demo/sft_qa/*.sample.jsonl`）。

## 2. 节点

统一结构：

```json
{
  "id": "math_7a_rjb_cpt17",
  "label": "Concept",
  "name": "相反数相加为零",
  "properties": {
    "definition": "互为相反数的两个数相加，结果等于0。",
    "importance": "了解"
  }
}
```

### 2.1 七类节点与字段

| label | 字段（properties 内） | 说明 |
|---|---|---|
| **Concept** | `definition`、`importance`（了解 \| 掌握 \| 重要）、`examples?`、`aliases?`、`formula?`、`unit?` | 概念 |
| **Skill** | `description`、`examples?` | 方法/技能 |
| **Experiment** | `instrument`、`is_student`（0 教师演示 \| 1 学生实操）、`process?`、`phenomena?`、`conclusion?` | 实验（**数学无此类节点**） |
| **Exercise** | `stem`、`answer`、`difficulty`（1–5）、`type`（选择/填空/判断/简答/证明/应用等）、`analysis?` | 习题 |
| **Book** | `subject`、`grade`、`publisher` | 教材册 |
| **Chapter** / **Section** | 章节名在 `name` | 章 / 节 |

- global_KG 的节点属性可能精简到 `name` 级别；完整属性以 `subject_specific_KG/*.json` 为准。
- 部分记录把属性平铺在顶层而非 `properties` 内，读取时两处都看。

### 2.2 ID 规范（`src/utils/k12_ids.py`）

```
{subject}_{book_code}_rjb_{type_code}{n}      例：math_7a_rjb_cpt17、chemistry_9a_rjb_exp3
{subject}_{book_code}_rjb_ch{n}               章    例：math_7a_rjb_ch2
{subject}_{book_code}_rjb_ch{n}_s{m}          节    例：math_7a_rjb_ch2_s3
```

- 类型码：`cpt` Concept、`skl` Skill、`exp` Experiment、`exe` Exercise。
- 册码（book_code）顺序：小学 `1a 1b 2a 2b 3a 3b 4a 4b 5a 5b 6a 6b`；初中 `7a 7b 8a 8b 9a 9 9b`；高中必修 `bx1 bx2 bx3`、选择性必修 `xzxbx1 xzxbx2 xzxbx3`。
- 全书前缀即 `math_9a_rjb` 这样的 book_prefix，共 48 册（math 23 / physics 9 / chemistry 7 / biology 9）。

## 3. 边

统一结构：

```json
{
  "source": "math_7a_rjb_cpt24",
  "source_name": "倒数",
  "target": "math_7a_rjb_cpt26",
  "target_name": "有理数除法法则",
  "type": "prerequisites_for",
  "properties": { "evidence": "除以一个数等于乘其倒数。" }
}
```

变体：习题侧用 `source_stem` 代替 `source_name`；一条记录映射多目标时用 `target_name_to_ids: [{target, target_name}, …]`。`properties.evidence` 为教材原文证据（字符串或 `{text}`）。

### 3.1 九类关系

| type | source → target | 语义 |
|---|---|---|
| `prerequisites_for` | Concept\|Skill\|Experiment → Concept\|Skill\|Experiment | **source 是 target 的先修**（方向别搞反） |
| `is_a` | Concept → Concept | 小概念属于大概念（从属/包含） |
| `relates_to` | Concept → Concept | 数形映射、成对/高关联概念；`properties.relations` 必含具体关联描述 |
| `verifies` | Experiment → Concept | 实验验证的原理 |
| `tests_concept` | Exercise → Concept | 习题考察的概念 |
| `tests_skill` | Exercise → Skill | 习题考察的方法 |
| `appears_in` | 知识 → Book/Chapter/Section | 教材出处 |
| `is_part_of` | 章节/知识 → 上级单元 | 结构包含 |
| `leads_to` | 知识 → 知识 | 学习进阶（与 prerequisites_for 同族，语义更松） |

## 4. K12-Bench

- 一行一道多选题（JSONL），5 个任务族、9 个文件：
  - `ground_subtask{1,2}.jsonl` — 把习题关联到它考察的概念/技能
  - `prereq_subtask{1,2}.jsonl` — 先修依赖与直接后继
  - `neighbor.jsonl` — 局部邻域的直接相关概念
  - `evidence_subtask{1,2}.jsonl` — 实验与所验证概念的连接
  - `locate_subtask{1,2}.jsonl` — 知识在课标中的位置与章节顺序
- 记录字段以文件首行为准（`head -1 xxx.jsonl` 看结构）；评测口径 EM / F1。
- 零样本基线（README 报告）：Gemini-3-Flash 57.1 EM / 73.0 F1 最佳；Prereq / Neighbor 任务 >40% 未解。

## 5. HuggingFace 加载

```python
from datasets import load_dataset
kg    = load_dataset("lhpku20010120/K12-KGraph", split="train")               # 图谱
bench = load_dataset("lhpku20010120/K12-KGraph", name="bench",  split="test") # K12-Bench
train = load_dataset("lhpku20010120/K12-KGraph", name="train",  split="train")# K12-Train
```

国内网络：`export HF_ENDPOINT=https://hf-mirror.com` 后重试，或直接用本技能 `scripts/fetch_data.sh`。

## 6. 引用

Hao Liang et al., 2026（PKU-DCAI）。论文 https://huggingface.co/papers/2605.09635 ｜ 项目页 https://haolpku.github.io/K12-KGraph-page/ 。数据 CC BY-NC-SA 4.0，代码 MIT。
