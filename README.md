# k12-kgraph-skill

> 让本地 AI Agent（ZCode / Claude Code 等支持 SKILL.md 的智能体）直接使用 **K12-KGraph** 教育知识图谱：查询知识点、追先修链、定位教材出处、拉取习题，生成学习路径与薄弱点根因诊断，产出课程锚定的练习与问答。
>
> 数据来源：[haolpku/K12-KGraph](https://github.com/haolpku/K12-KGraph)（北京大学 PKU-DCAI，NeurIPS 2026）｜ 数据许可 **CC BY-NC-SA 4.0**（禁商用）

---

## 目录

1. [这是什么](#1-这是什么)
2. [工作原理](#2-工作原理)
3. [安装](#3-安装)
4. [快速开始](#4-快速开始)
5. [正确的使用方法](#5-正确的使用方法)
6. [kg.py 命令参考](#6-kgpy-命令参考)
7. [已知限制与坑](#7-已知限制与坑)
8. [目录结构](#8-目录结构)
9. [FAQ / 故障排查](#9-faq--故障排查)
10. [许可与致谢](#10-许可与致谢)

---

## 1. 这是什么

[K12-KGraph](https://github.com/haolpku/K12-KGraph) 是北京大学发布的课标知识图谱：基于人教版 48 册教材抽取，覆盖数学 / 物理 / 化学 / 生物（K1–K12），共 **10,685 节点 / 23,278 边**，含 7 类节点（Book / Chapter / Section / Concept / Skill / Experiment / Exercise）和 9 类关系（先修、从属、关联、验证、考察、出处等），并附带 K12-Bench 评测集（23,640 题）与 K12-Train 训练语料。

**本 skill 解决的问题**：Agent 直接读这份数据需要先学会它的 schema、ID 规范和数据获取方式——每次对话都重新解释一遍既费 token 又容易出错。本 skill 把这些固化下来，Agent 在被触发后按既定工作流调用附带脚本即可正确使用数据。

**装上后 Agent 能做什么**：

| 能力 | 说明 |
|---|---|
| 知识点查询 | 概念定义、重要程度（了解/掌握/重要）、公式、别名 |
| 先修链追溯 | 前置知识集合 + 建议补学顺序（拓扑排序，自动处理数据中的环） |
| 教材定位 | 知识点 → 册 / 章 / 节（"人教版七上 第2章"） |
| 习题召回 | 考察某知识点的课后习题（题干 / 答案 / 难度） |
| 学习路径 / 根因诊断 | 沿先修边逆流回溯薄弱点，输出路径表 |
| 课程锚定出题 / QA | 基于 definition / evidence / stem 生成有出处的教学内容 |
| 评测引导（进阶） | 引导使用 K12-Bench 与官方 eval 管线评测模型 |

## 2. 工作原理

### 2.1 Skill 的三层渐进加载（progressive disclosure）

```
Agent 启动
  └─ 只加载元数据（SKILL.md 的 name + description）→ 常驻上下文，用于判断"要不要触发"
用户提问命中触发词（知识点 / 先修 / 学习路径 / 人教版…）
  └─ 加载 SKILL.md 正文 → 选工作流（§5 的 A–D），读数据获取与 schema 速查
工作流需要执行
  └─ 调用 scripts/（按需），深度细节按需读 references/schema.md
```

description 决定触发率，正文决定执行质量，`scripts/` 和 `references/` 不占日常上下文——这是本 skill 结构上刻意做的取舍：正文保持在几百行内，字段级 schema 放进 `references/schema.md`。

### 2.2 数据流

```
HuggingFace 数据集（国内走 hf-mirror）
   │  scripts/fetch_data.sh core|all（抓取）／ update（更新缓存）
   ▼
~/.cache/k12-kgraph/（本地缓存，可换目录）
   │  scripts/kg.py 加载并归一化
   ▼
命令输出（稳定的英文键 + 原始中文数据）
   │  Agent 按 SKILL.md 约定改写
   ▼
给用户的 Markdown 表格 / 诊断报告 / 练习题
```

`fetch_data.sh update` 对已缓存文件做条件请求（If-Modified-Since），只拉取真正变更的文件、跳过未变化的、自动补上缺失的 core 文件；下载走临时文件原子替换，请求失败（4xx/5xx/网络错误）不会污染已有缓存。

### 2.3 kg.py 在底层做了什么

- **多源合并**：递归扫描数据目录（深度 ≤3），把 `global_KG`（属性精简的全局图）与 `subject_specific_KG`（属性丰富的学科图）合并且后者覆盖前者，查询结果自动带完整定义 / 公式。
- **形态兼容**：同时支持 `{nodes, edges}` 合体文件（demo、学科图）与 `nodes.json` / `edges.json` 裸数组分离文件（global_KG），并对字段名做了归一化（`id`/`node_id`、`source`/`from` 等）。
- **环防御**：上游数据的先修图被实证存在环（见 [issue #8](https://github.com/haolpku/K12-KGraph/issues/8)），`prereq --transitive` 的学习顺序输出会**自动破环并给出警告**，`check-cycles` 可随时复查——不要把"先修图无环"当事实。
- **零依赖**：纯 Python 标准库，不需要 pip 安装任何包。

## 3. 安装

skill 遵循通用 `SKILL.md` 规范，任何支持该规范的 Agent 平台都可使用。以 ZCode 为例：

```bash
# 用户级安装（所有项目可用）
git clone git@github.com:gbwxy/k12-kgraph-skill.git ~/.zcode/skills/k12-kgraph-skill

# 或项目级安装（只在某个项目内可用，便于随仓库分发）
git clone git@github.com:gbwxy/k12-kgraph-skill.git <你的项目>/.agents/skills/k12-kgraph-skill
```

> **重要：目录名必须与 SKILL.md frontmatter 的 `name` 字段一致（均为 `k12-kgraph-skill`）**，否则 Agent 可能发现不了这个 skill。如果你改了目录名，请同步修改 `SKILL.md` 第一行的 `name`。

安装后**新开会话**生效（skill 发生在会话启动时）。验证：对 Agent 说"帮我查一下倒数这个知识点"，若它开始调用 `kg.py` 即安装成功。

## 4. 快速开始

```bash
# ① 拉取数据（core = 全局图 + 4 学科图，约 13 MB，日常查询够用）
bash ~/.zcode/skills/k12-kgraph-skill/scripts/fetch_data.sh core

# ② 命令行直接验证（可选）
python3 ~/.zcode/skills/k12-kgraph-skill/scripts/kg.py find 倒数

# ③ 对 Agent 用自然语言提问
#    "帮我查'一元二次方程'的先修知识链，给出补学顺序"
```

之后数据过期或上游修复（比如 issue #8 的环修好）时，**更新缓存**即可，无需重装：

```bash
bash ~/.zcode/skills/k12-kgraph-skill/scripts/fetch_data.sh update
```

网络说明：`fetch_data.sh` 默认走 `https://hf-mirror.com`（国内可直连）；海外或想走官方源：

```bash
HF_ENDPOINT=https://huggingface.co bash scripts/fetch_data.sh core
```

不想下载全量时，也可以直接指向 [上游仓库](https://github.com/haolpku/K12-KGraph) 的 `demo/kg/math_7a_rjb.json`（七上数学单册样例）体验：

```bash
python3 scripts/kg.py --data /path/to/K12-KGraph/demo/kg/math_7a_rjb.json stats
```

## 5. 正确的使用方法

### 5.1 用自然语言触发

skill 由这些话题触发（不必点名 skill）：

- "查一下 XX 知识点" / "XX 的定义和公式"
- "学 XX 之前要先学什么" / "先修知识" / "前置知识"
- "XX 在教材哪一册哪一章"
- "有哪些题考 XX" / "出几道 XX 的练习"
- "孩子 XX 老是学不会，帮我找根因" / "薄弱点回溯" / "学习路径"

### 5.2 使用前提（先看这里，能避免 90% 的问题）

1. **数据先落地**：`kg.py` 不联网、不会自动下载数据。没数据时它会报错并提示跑 `fetch_data.sh`——这不是 bug。
2. **关键词用核心词**："倒数"而不是"求一个数的倒数的方法"；搜不到先试更短的词。
3. **引用输出时保留出处**：数据许可 CC BY-NC-SA 4.0，对外材料注明"数据来源 K12-KGraph"，且**禁止商用**。

### 5.3 四个典型场景

**场景 A · 知识点查询 / 备课**（你说 → Agent 做 → 你得到）

> "人教版'倒数'这个知识点在教材哪里？有什么例题？"
> → Agent 执行 `find 倒数` → `show <id>` → `locate <id>` → `exercises <id>`
> → 你得到：定义 / 重要程度 / 教材出处 / 1–N 道带答案的习题

**场景 B · 学习路径 / 薄弱点根因诊断**

> "孩子'有理数除法'总错，帮我诊断一下该补哪些知识"
> → Agent 执行 `prereq <id> --transitive`（拿先修集合 + 拓扑补学顺序）→ 对每个先修点 `exercises` 选低难度验证题
> → 你得到：按建议顺序排列的路径表

```markdown
| 顺序 | 知识点 | 重要程度 | 教材出处 | 建议练习 |
|---|---|---|---|---|
| 1 | 倒数(math_7a_rjb_cpt24) | 掌握 | 七上 第2章 | exe1 |
| 2 | 有理数除法法则(math_7a_rjb_cpt26) | 重要 | 七上 第2章 | exe2 |
```

**场景 C · 课程锚定出题 / QA 生成**

> "围绕'倒数'出 3 道填空题，要有出处"
> → Agent 取 `show` 的 definition/formula + 边的 `evidence`（教材原文证据）作锚点生成
> → 你得到：标注出处的题目 + "AI 生成，需教师审校"提醒

**场景 D · 模型评测（进阶）**："用 K12-Bench 测一下这个模型" → Agent 引导 `fetch_data.sh all` 后走上游 `eval/run.sh`（需要 API key 或 GPU）。

### 5.4 输出解读

- `suggested_learning_order` 的顺序即补学顺序（先修在前）；出现 `warning: N cycle(s) broken` 不是脚本故障，是上游数据问题（§7），顺序已自动破环、可放心用。
- 边上的 `evidence` 是教材原文证据，适合直接引用到备课材料。
- 诊断结论是**参考建议**，不替代教师判断（数据由 LLM 辅助抽取，见 §7）。

## 6. kg.py 命令参考

```bash
python3 scripts/kg.py [--data DIR|FILE] COMMAND [ARGS]
```

`--data` 缺省时依次找 `$K12KGRAPH_DATA`、`~/.cache/k12-kgraph`。

| 命令 | 用途 | 示例 |
|---|---|---|
| `stats` | 节点 / 边规模统计 | `kg.py stats` |
| `find KEYWORD [--label L]` | 按名称 / 别名 / 定义搜索 | `kg.py find 倒数` |
| `show ID` | 节点详情 + 全部关系 | `kg.py show math_7a_rjb_cpt24` |
| `prereq ID [--transitive] [--depth N]` | 先修链 + 建议学习顺序 | `kg.py prereq math_7a_rjb_cpt26 --transitive` |
| `path FROM TO` | 先修路径（FROM 是 TO 的祖先） | `kg.py path A B` |
| `locate ID` | 教材出处（册 < 章 < 节） | `kg.py locate math_7a_rjb_cpt24` |
| `exercises ID` | 考察该点的习题 | `kg.py exercises math_7a_rjb_cpt24` |
| `neighbors ID` | is_a / relates_to / leads_to 邻居 | `kg.py neighbors math_7a_rjb_cpt1` |
| `check-cycles [--all]` | 环检测 | `kg.py check-cycles` |

节点 ID 形如 `math_7a_rjb_cpt24` = 数学·七年级上册·人教版·概念24（`cpt/skl/exp/exe` = 概念/技能/实验/习题）；完整 ID 规范见 `references/schema.md`。

## 7. 已知限制与坑

1. **先修图存在环**（上游 [issue #8](https://github.com/haolpku/K12-KGraph/issues/8)，未修复）：`check-cycles` 可复现，学习顺序已自动破环，但**不要直接对原始数据做拓扑排序**。
2. **数据是 AI 辅助抽取 + 专家评审**（Fleiss' κ = 0.84）：日常查询可信；直接影响学生的高风险结论（如分班、诊断定论）请人工复核。
3. **只覆盖人教版（rjb）**；北师大 / 苏教版不在范围内。
4. **数学没有 Experiment 节点**（物理 / 化学 / 生物才有），数学相关的实验类问题无数据。
5. **K12-Bench 是多选题**（EM / F1 口径），评估能力时注意题型局限。
6. **许可**：数据 CC BY-NC-SA 4.0 —— **禁止商用**，衍生数据需同许可，引用需署名。

## 8. 目录结构

```
k12-kgraph-skill/
├── SKILL.md              # Agent 的行为说明：触发条件、数据获取、4 类任务工作流
├── README.md             # 本文件（面向人）
├── scripts/
│   ├── kg.py             # 查询 CLI（纯标准库）：9 个子命令，见 §6
│   └── fetch_data.sh     # 数据下载/更新：core（图谱）/ all（+ 习题 + Bench + Train）/ update（更新缓存）
└── references/
    └── schema.md         # 字段级 schema：7 节点型、9 关系语义、ID 规范、文件布局
```

## 9. FAQ / 故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| `error: no data found` | 数据未下载 | `bash scripts/fetch_data.sh core`，或 `--data` 指定路径 |
| `find` 总是没结果 | 关键词太长 / 数据没加载 | 用核心词；先跑 `stats` 确认加载正常 |
| 输出里有 `warning: cycle(s) broken` | 上游数据的环（issue #8） | 正常现象，顺序已破环；详情用 `check-cycles` |
| 下载超时 / 连不上 huggingface.co | 国内网络 | 默认已走 hf-mirror；确认没手动改 `HF_ENDPOINT` |
| 数据过期了 / issue #8 修复后怎么换新数据 | 缓存是本地快照 | `bash scripts/fetch_data.sh update`（只拉变更，失败不覆盖旧数据） |
| 装好了但 Agent 不触发 | 目录名与 `name` 不一致，或还在旧会话 | 目录名保持 `k12-kgraph-skill`（或同步改 `name`）；新开会话 |
| 想查的学科数据没有 | `core` 只含图谱 | `bash scripts/fetch_data.sh all` 补课后习题 / Bench / Train |

## 10. 许可与致谢

- **数据**（K12-KGraph 图谱 / Bench / Train）：[CC BY-NC-SA 4.0](https://github.com/haolpku/K12-KGraph/blob/main/LICENSE) © 北京大学 PKU-DCAI —— 禁止商用，使用请注明 *数据来源 K12-KGraph*。
- **本 skill 的脚本与文档**：以本仓库 LICENSE 文件为准；如未添加 LICENSE，默认保留所有权利（欢迎补一个 MIT）。
- 致谢：[haolpku/K12-KGraph](https://github.com/haolpku/K12-KGraph) · [HuggingFace 数据集](https://huggingface.co/datasets/lhpku20010120/K12-KGraph) · [论文](https://huggingface.co/papers/2605.09635) · [项目主页](https://haolpku.github.io/K12-KGraph-page/)
