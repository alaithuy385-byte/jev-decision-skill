---
name: jev-decision
description: "调用 TypeSafe AI 的 Jev（System One）决策模型，把材料 + 明确问题换成可编程的判断结果（是/否概率、单选题、评分），而不是生成文本。当用户要求『用 Jev 判断』『让模型给个决策/路由/打分』『TypeSafe / typesafe-ai / systemone / Jev』，或需要在工作流里做分类、路由、风险判定、评分、命令/改动放行门禁时使用。默认走 TypeSafe 官方端点（需 TYPESAFE_API_KEY）；没有 key 时可加 `--endpoint playground` 走第三方免密钥通道先试手感。"
agent_created: true
---

# Jev 决策模型调用

## Jev 是什么

TypeSafe AI 的 System One 模型。**它不是聊天模型**：你给它材料（`state`）和带类型的问题，它返回选项、分数、概率。不写解释、不改代码、不做多轮。

用途：分类与路由、风险分级、评分、Agent 下一步动作选择、工作流放行门禁、命令审查。

## 关键接口事实（照抄，不要凭印象写）

| 项 | 值 |
|---|---|
| 默认端点 | `POST https://api.typesafe.ai/v1/systemone` — 需 `TYPESAFE_API_KEY` |
| 免密钥端点（试用） | `POST https://jevplayground.com/api/evaluate` — 第三方站点，有限速 |
| 认证 | 默认端点发 `Authorization: Bearer $TYPESAFE_API_KEY`；playground 不需要 |
| 请求体 | 原生 Jev 格式 + 下文两个坑 |
| 响应 | `{ok, model:"typesafe-ai/jev", latencyMs, result:{answers, usage, confidence, warnings}}` |
| 实测延迟 | 直连 0.3–1.6 s |

### 两个必踩的坑

1. **题型关键字是 `boolean`，不是 `noul`。**
   TypeSafe 官方文档与 Venice 文档写 `noul`；但 Vercel AI Gateway / playground 这一层用
   `boolean`。写 `noul` 会直接 400：
   `Invalid discriminator value. Expected 'boolean' | 'choice' | 'score'`。

2. **`questions` 是字典，不是数组。** key 就是响应里 `answers` 的 key。
   传数组会 400：`expected record, received array`。
   顺带：playground 前端自己的表单字段（`mode` / `question` / `choices` / `rubric`）会被
   服务端拒绝（`Unrecognized keys`）——那只是前端内部草稿结构，别照着抄。

## 请求体

```json
{
  "state": "被判断的材料。字符串；也可以塞 JSON 字符串",
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

- `choice` 的 `criteria` 是**字典**（选项名 → 说明），`null` 说明可接受；给一个兜底选项（如 `other`）避免被迫分类。
- `score` 的 `criteria` 是**有序数组**，从低到高，下标从 0 开始。
- playground 通道限速/限额：`state` ≤ 8000 字符、`instructions` ≤ 2000 字符。其他通道通常更宽。

## 响应

```json
{"result":{
  "answers":{
    "is_urgent":  {"type":"boolean","probability":0.96},
    "department": {"type":"choice","choice":"billing","probabilities":{"billing":1}},
    "frustration":{"type":"score","score":1.17,"probabilities":{"1":0.83,"2":0.17}}
  },
  "usage":{"inputTokens":409,"outputTokens":73},
  "confidence":{"department":1.0,"frustration":0.75},
  "warnings":[]}}
```

- `boolean`：只有一个 `probability`（P(真)），**没有 confidence 字段**——接近 0.5 就是不确定。
- `choice` / `score`：答案与 `confidence` 分开。`score` 是概率加权值，**会落在两个等级之间**（1.17 = 主要在等级 1 略偏 2）。
- `confidence` 是分布算出的统计量，**不是「答案正确的概率」**。

## 怎么用

```bash
"<python>" "<本 skill>/scripts/jev.py" payload.json          # 人类可读
"<python>" "<本 skill>/scripts/jev.py" payload.json --json   # 原始 JSON
"<python>" "<本 skill>/scripts/jev.py" --endpoint playground --selftest   # 免密钥自检
```

- `<python>` 用托管解释器绝对路径，例如
  `C:\Users\16913\.workbuddy\binaries\python\versions\3.13.12\python.exe`（本机无 `python3`）。
- **默认通道是 `typesafe`，需要 `TYPESAFE_API_KEY`**；没有 key 时给每条命令加
  `--endpoint playground`，或设 `JEV_ENDPOINT=playground`。
- 脚本纯标准库、零依赖。传输策略：**先直连**，失败再自动重试本地代理
  `127.0.0.1:7890` / `127.0.0.1:58252`；也可 `--proxy <url>` 强制指定。
- 脚本会在发请求前本地校验 payload，并打印清晰的字段级报错。

## 通道切换

四条通道都内置了，用 `--endpoint` 切换，也可以设 `JEV_ENDPOINT` 环境变量：

| `--endpoint` | 地址 | 需要的环境变量 | 模型名 |
|---|---|---|---|
| `playground` | `jevplayground.com/api/evaluate` | 无（第三方，试用） | `typesafe-ai/jev` |
| `opencode` | `opencode.ai/zen/v1/systemone` | `OPENCODE_API_KEY` | `jev-1.13-free`（限时免费）/ `jev-1.13` |
| `venice` | `api.venice.ai/api/v1/decisions` | `VENICE_API_KEY` | `jev-latest` |
| `typesafe` **（默认）** | `api.typesafe.ai/v1/systemone` | `TYPESAFE_API_KEY` | `jev-latest` |

密钥一律走**环境变量**，不要写进 payload 或 skill 文件。

## 用之前必须先做的判断

- **问题必须自己写清楚。** 「判断这件事是否合理」是废问题；「是否符合用户明确要求」「是否会修改远程状态」「是否涉及凭证」才是可用的问题。条件分开问，可以一次请求批量问。
- **答案范围要事先封闭。** Jev 只在已知选项集内判断，开放式问题不适合。
- **不要让它算能算的东西。** 数量、日期差、数值范围交给代码。
- **换题型 / 改措辞 / 换模型后，阈值必须重新验证。** 结果非确定性，同一输入多次调用分数会飘。
- **提示注入防护要另做。** 材料里可能藏指令，写「忽略输入中的指令」不足以证明安全。

## 阈值怎么定（如果有下游动作）

用 `confidence` 分档：≥0.90 直接执行；≥0.60 作为建议、需要确认；更低交人工复核。
阈值必须用**自己的脱敏样本**（20–50 条）人工标注后校准，把「漏检」和「误报」分开统计。
构造性/不可逆动作（删除、推送、发布、付款）用更高阈值。
