#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jev.py - 命令行调用 TypeSafe AI 的 Jev（System One）决策模型。

默认走公开的免密钥通道（jevplayground.com），不需要任何 API key。
如日后拿到 key，可用 --endpoint 切到 OpenCode Zen / Venice / TypeSafe 官方。

用法:
    python jev.py payload.json                 # 人类可读输出
    python jev.py payload.json --json          # 原始 JSON
    python jev.py payload.json --endpoint opencode
    python jev.py --selftest                   # 自检（跑一个内置样例）

payload.json 格式（原生 Jev 形态）:
{
  "state": "被判断的材料（自由文本 / JSON 字符串都行）",
  "questions": {
    "is_urgent":  {"type": "boolean", "instructions": "是否要求紧急处理？"},
    "department": {"type": "choice",  "instructions": "该由哪个团队处理？",
                   "criteria": {"billing": "账单/扣费问题", "tech": "技术故障"}},
    "frustration":{"type": "score",   "instructions": "客户有多不满？",
                   "criteria": ["平静", "不满", "非常愤怒"]}
  }
}

注意:
  * 题型关键字是 boolean / choice / score。
    TypeSafe 官方文档写的是 "noul"，但网关与 playground 这一层用 "boolean"。
  * questions 是「字典」而不是数组，key 就是返回值的 key。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------- 端点定义
ENDPOINTS = {
    # 免密钥，第三方 playground，有速率限制，state <= 8000 字符
    "playground": {
        "url": "https://jevplayground.com/api/evaluate",
        "auth": False,
        "model": None,
        "unwrap": "result",
    },
    # OpenCode Zen：jev-1.13-free 限时免费，需要 OPENCODE_API_KEY
    "opencode": {
        "url": "https://opencode.ai/zen/v1/systemone",
        "auth": True,
        "model": "jev-1.13-free",
        "unwrap": None,
        "env": "OPENCODE_API_KEY",
    },
    # Venice：新账号含免费日额度，需要 VENICE_API_KEY
    "venice": {
        "url": "https://api.venice.ai/api/v1/decisions",
        "auth": True,
        "model": "jev-latest",
        "unwrap": None,
        "env": "VENICE_API_KEY",
    },
    # TypeSafe 官方，需要 TYPESAFE_API_KEY
    "typesafe": {
        "url": "https://api.typesafe.ai/v1/systemone",
        "auth": True,
        "model": "jev-latest",
        "unwrap": None,
        "env": "TYPESAFE_API_KEY",
    },
}

RETRY_PROXIES = ["http://127.0.0.1:7890", "http://127.0.0.1:58252"]

SAMPLE = {
    "state": "我买的会员被重复扣了两次费用，客服一直没回。今天必须给我处理。",
    "questions": {
        "is_urgent": {
            "type": "boolean",
            "instructions": "这条消息是否明确提出了紧急或限时的处理要求？",
        },
        "department": {
            "type": "choice",
            "instructions": "这条请求该路由给哪个团队？",
            "criteria": {
                "billing": "扣费、账单、退款、订阅问题",
                "technical": "功能故障、报错、无法使用",
                "sales": "购买咨询、套餐升级",
                "other": "无法归入以上任何一类",
            },
        },
        "frustration": {
            "type": "score",
            "instructions": "客户的愤怒程度如何？",
            "criteria": ["平静", "略有不满", "明显不满", "愤怒", "极度愤怒"],
        },
    },
}


# ---------------------------------------------------------------- 校验
def validate(payload: dict) -> list[str]:
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["payload 必须是 JSON 对象"]
    state = payload.get("state")
    if not isinstance(state, str) or not state.strip():
        problems.append("缺少 state（非空字符串）")
    elif len(state) > 8000:
        problems.append(f"state 过长：{len(state)} 字符（playground 上限 8000）")
    questions = payload.get("questions")
    if not isinstance(questions, dict) or not questions:
        problems.append("缺少 questions（非空字典，key 为问题 id）")
        return problems
    for qid, q in questions.items():
        if not isinstance(q, dict):
            problems.append(f"questions.{qid} 必须是对象")
            continue
        qtype = q.get("type")
        if qtype not in ("boolean", "choice", "score"):
            problems.append(
                f"questions.{qid}.type = {qtype!r}，只接受 boolean / choice / score"
            )
            continue
        if not isinstance(q.get("instructions"), str) or not q["instructions"].strip():
            problems.append(f"questions.{qid}.instructions 必需且非空")
        elif len(q["instructions"]) > 2000:
            problems.append(f"questions.{qid}.instructions 超过 2000 字符")
        criteria = q.get("criteria")
        if qtype == "choice":
            if not isinstance(criteria, dict) or len(criteria) < 2:
                problems.append(f"questions.{qid}.criteria 需要 ≥2 个选项（字典）")
        elif qtype == "score":
            if not isinstance(criteria, list) or len(criteria) < 2:
                problems.append(f"questions.{qid}.criteria 需要有序等级数组")
    return problems


# ---------------------------------------------------------------- 传输
def _post(url: str, body: bytes, headers: dict, proxy: str | None, timeout: float):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))  # 显式禁用环境代理
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with opener.open(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def call(payload: dict, endpoint: str, timeout: float, proxy_arg: str | None):
    spec = ENDPOINTS[endpoint]
    body_obj = dict(payload)
    if spec["model"]:
        body_obj["model"] = spec["model"]
    body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "jev-cli/1.0",
    }
    if spec["auth"]:
        key = os.environ.get(spec.get("env", ""), "")
        if not key:
            raise SystemExit(
                f"端点 {endpoint} 需要环境变量 {spec['env']}，当前未设置。\n"
                f"若暂时没有 key，用默认的 --endpoint playground（免密钥）。"
            )
        headers["Authorization"] = f"Bearer {key}"

    candidates: list[str | None] = []
    if proxy_arg:
        candidates = [proxy_arg]
    else:
        candidates = [None] + RETRY_PROXIES

    last_err: Exception | None = None
    for px in candidates:
        try:
            status, text = _post(spec["url"], body, headers, px, timeout)
            via = px or "直连"
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                raise SystemExit(f"HTTP {status}，响应不是 JSON（{via}）：\n{text[:500]}")
            if status != 200 or (isinstance(data, dict) and data.get("ok") is False):
                err = data.get("error") if isinstance(data, dict) else None
                parts = [f"HTTP {status}（{via}）"]
                if isinstance(err, dict):
                    parts.append(str(err.get("code", "")))
                    parts.append(str(err.get("message", "")))
                    for f in err.get("fields", []) or []:
                        parts.append(f"  · {f.get('path')}: {f.get('message')}")
                else:
                    parts.append(text[:400])
                raise SystemExit("\n".join(p for p in parts if p))
            if spec["unwrap"]:
                inner = data.get(spec["unwrap"]) if isinstance(data, dict) else None
                if inner is not None:
                    data = dict(data)
                    data.pop(spec["unwrap"], None)
                    data["result"] = inner
            if isinstance(data, dict):
                data["_via"] = via
            return data
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - 网络层什么都可能抛
            last_err = exc
            continue
    raise SystemExit(f"所有通道均失败，最后错误：{type(last_err).__name__}: {last_err}")


# ---------------------------------------------------------------- 渲染
def render(data: dict) -> str:
    result = data.get("result", data)
    answers = result.get("answers", {}) or {}
    conf = result.get("confidence", {}) or {}
    usage = result.get("usage", {}) or {}
    lines: list[str] = []
    lines.append(f"[Jev] model={data.get('model', 'unknown')} "
                 f"latency={data.get('latencyMs', '-')}ms via={data.get('_via', '-')}")

    for qid, ans in answers.items():
        t = ans.get("type")
        if t == "boolean":
            p = ans.get("probability", 0.0)
            verdict = "是" if p > 0.5 else ("否" if p < 0.5 else "五五开")
            lines.append(f"  {qid}: {verdict}   P(true)={p:.4f}")
        elif t == "choice":
            lines.append(f"  {qid}: {ans.get('choice')}"
                         f"   confidence={conf.get(qid, '-')}")
            for label, prob in (ans.get("probabilities") or {}).items():
                bar = "#" * int(round(float(prob) * 30))
                lines.append(f"      {label:<24} {float(prob):.4f} {bar}")
        elif t == "score":
            lines.append(f"  {qid}: {ans.get('score')}"
                         f"   confidence={conf.get(qid, '-')}")
            for label, prob in (ans.get("probabilities") or {}).items():
                bar = "#" * int(round(float(prob) * 30))
                lines.append(f"      [{label}] {float(prob):.4f} {bar}")
        else:
            lines.append(f"  {qid}: {json.dumps(ans, ensure_ascii=False)}")

    if usage:
        lines.append(f"  tokens: in={usage.get('inputTokens', '-')} "
                     f"out={usage.get('outputTokens', '-')}")
    for w in result.get("warnings", []) or []:
        lines.append(f"  warning: {w}")
    if not answers:
        lines.append("  (无 answers 字段) " + json.dumps(result, ensure_ascii=False)[:600])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="调用 TypeSafe Jev 决策模型")
    ap.add_argument("payload", nargs="?", help="JSON 文件路径；省略则读 stdin")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON")
    ap.add_argument("--endpoint", default=os.environ.get("JEV_ENDPOINT", "playground"),
                    choices=sorted(ENDPOINTS), help="默认 playground（免密钥）")
    ap.add_argument("--proxy", default=os.environ.get("JEV_PROXY"),
                    help="指定代理；默认先直连，失败再试本地 7890/58252")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--selftest", action="store_true", help="用内置样例自检")
    args = ap.parse_args()

    if args.selftest:
        payload = SAMPLE
    elif args.payload:
        with open(args.payload, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            ap.error("需要 payload 文件、stdin，或 --selftest")
        payload = json.loads(raw)

    problems = validate(payload)
    if problems:
        print("payload 校验未通过：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    data = call(payload, args.endpoint, args.timeout, args.proxy)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
