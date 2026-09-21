# jev-decision-skill

> 让 AI Agent 直接调上 **TypeSafe AI「Jev」** 决策模型的 Agent Skill —— **不需要任何 API key**。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
![Python](https://img.shields.io/badge/Python-3.8%2B%20stdlib-blue)
![Deps](https://img.shields.io/badge/dependencies-none-brightgreen)

---

## 这是什么

**Jev** 是 TypeSafe AI 推出的 *System One* 模型。它和聊天模型不是一类东西：

| | 聊天模型 | **Jev** |
|---|---|---|
| 输出 | 一段话 / JSON | 选项、分数、概率 |
| 用途 | 生成内容 | **做判断** |
| 单次请求 | 一问一答 | 支持并行多个带类型的问题 |
| 谁消费结果 | 人 | **代码** |

你给它材料（`state`）和带类型的问题，它返回机器可直接用的判断结果。适合：

- 分类与路由（工单该给谁 / 这条消息属于哪类）
- 风险分级（这个改动有多危险）
- 评分（紧急度、愤怒度、严重度）
- Agent 下一步动作选择
- 工作流 / 命令放行门禁

本 Skill 把 Jev 包成一个**零依赖、开箱即用**的命令行工具，默认走免密钥通道，装上就能跑。

---

## 30 秒上手

```bash
python scripts/jev.py --selftest
```

输出：

```
[Jev] model=typesafe-ai/jev latency=330.73ms via=直连
  is_urgent: 是   P(true)=0.9700
  department: billing   confidence=1
      billing                  1.0000 ##############################
      technical                0.0000
      sales                    0.0000
      other                    0.0000
  frustration: 2.99   confidence=0.91
      [3] 0.8900 ###########################
  tokens: in=504 out=80
```

自定义判断：写一个 JSON 丢给它。

```bash
python scripts/jev.py payload.json          # 人类可读
python scripts/jev.py payload.json --json   # 原始 JSON，喂给下游代码
```

---

## 安装（作为 Agent Skill）

把仓库放进你的 skills 目录即可：

```bash
git clone https://github.com/<你的用户名>/jev-decision-skill.git

# WorkBuddy / CodeBuddy
mv jev-decision-skill ~/.workbuddy/skills/jev-decision

# Claude Code
mv jev-decision-skill ~/.claude/skills/jev-decision
```

Agent 会在遇到「用 Jev 判断 / 给个路由 / 打个分 / 风险分级」这类请求时自动加载。

**唯一要求：Python 3.8+（只用标准库，无需 pip install）。**

---

## 请求格式

```json
{
  "state": "被判断的材料，字符串（也可以塞 JSON 字符串）",
  "questions": {
    "is_urgent": {
      "type": "boolean",
      "instructions": "这条消息是否明确提出了紧急处理要求？"
    },
    "department": {
      "type": "choice",
      "instructions": "该路由给哪个团队？",
      "criteria": {
        "billing": "扣费、账单、退款、订阅问题",
        "technical": "功能故障、报错、无法使用",
        "other": null
      }
    },
    "frustration": {
      "type": "score",
      "instructions": "客户愤怒程度？",
      "criteria": ["平静", "略有不满", "明显不满", "愤怒", "极度愤怒"]
    }
  }
}
```

### 三种题型

| `type` | 返回 | 说明 |
|---|---|---|
| `boolean` | `probability` (0–1) | P(真)。**没有 confidence 字段** —— 接近 0.5 就是不确定 |
| `choice` | `choice` + `probabilities` + `confidence` | 分类 / 路由。给一个兜底选项（如 `other`） |
| `score` | `score` + `probabilities` + `confidence` | 有序等级，下标从 0 起。分数是**概率加权值**，会落在两级之间 |

```json
{"answers": {
  "is_urgent":  {"type": "boolean", "probability": 0.96},
  "department": {"type": "choice",  "choice": "billing", "probabilities": {"billing": 1}},
  "frustration":{"type": "score",   "score": 1.17, "probabilities": {"1": 0.83, "2": 0.17}}
},
"confidence": {"department": 1.0, "frustration": 0.75},
"usage": {"inputTokens": 409, "outputTokens": 73}}
```

---

## 两个必踩的坑

本仓库最大的价值可能就在这两行 —— 官方文档会让你第一发就 400。

1. **题型关键字是 `boolean`，不是 `noul`。**
   TypeSafe 官方文档和 Venice 文档写 `noul`，但 Vercel AI Gateway / playground 这一层用 `boolean`。
   写 `noul` 直接报 `Invalid discriminator value. Expected 'boolean' | 'choice' | 'score'`。

2. **`questions` 是字典，不是数组。** key 就是响应里 `answers` 的 key。
   传数组报 `expected record, received array`。
   （前端表单里的 `mode` / `question` / `choices` / `rubric` 是前端内部草稿结构，服务端会以 `Unrecognized keys` 拒绝。）

---

## 接入通道

脚本内置 4 条通道，用 `--endpoint` 切换。密钥一律走**环境变量**。

| `--endpoint` | 地址 | 密钥 | 模型名 |
|---|---|---|---|
| `playground` **(默认)** | `jevplayground.com/api/evaluate` | **不需要** | `typesafe-ai/jev` |
| `opencode` | `opencode.ai/zen/v1/systemone` | `OPENCODE_API_KEY` | `jev-1.13-free` / `jev-1.13` |
| `venice` | `api.venice.ai/api/v1/decisions` | `VENICE_API_KEY` | `jev-latest` |
| `typesafe` | `api.typesafe.ai/v1/systemone` | `TYPESAFE_API_KEY` | `jev-latest` |

```bash
JEV_ENDPOINT=venice VENICE_API_KEY=xxx python scripts/jev.py payload.json
# 或
python scripts/jev.py payload.json --endpoint venice
```

其他命令行参数：`--json`、`--proxy <url>`、`--timeout <秒>`、`--selftest`。
网络策略：**先直连，失败自动重试本地代理** `127.0.0.1:7890` / `127.0.0.1:58252`。

> **隐私提醒**：默认的 playground 是**第三方站点**，你发送的 `state` 会完整落到它那里。
> 审代码 diff、客户消息这类材料请先脱敏。需要更强隐私保证时用 Venice（不保留 state、不用于训练）。

---

## 用法要点

**问题必须自己写清楚。**
「判断这件事是否合理」是废问题；「是否符合用户明确要求」「是否会修改远程状态」「是否涉及凭证」才是可用的问题。条件分开问，一次请求可以批量问。

**答案范围要事先封闭。** 开放式问题不该交给 Jev。

**能算的交给代码。** 数量、日期差、数值范围别让模型猜。

**阈值要拿自己的样本调。** `confidence` 分档的常见做法：≥0.90 直接执行；≥0.60 作为建议、需确认；更低转人工。
但阈值必须用 20–50 条脱敏样本人工标注后校准，把「漏检」和「误报」分开统计。构造性动作（删除、推送、发布、付款）用更高阈值。

**结果非确定性。** 同一输入多次调用分数会飘；换题型、改措辞、换模型后，阈值必须重新验证。

**`confidence` 不是「答案正确的概率」**，它是从概率分布算出的统计量。

---

## 目录结构

```
jev-decision-skill/
├── SKILL.md               # Agent 加载的 Skill 定义（接口事实 + 使用规范）
├── scripts/
│   └── jev.py             # 零依赖 CLI：校验 + 调用 + 渲染
├── examples/
│   ├── support-triage.json    # 客服工单分类与紧急度
│   └── command-gate.json      # Agent 命令放行门禁
├── LICENSE
└── README.md
```

---

## License

MIT
