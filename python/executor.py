#!/usr/bin/env python3
"""声明式接入层的通用执行器。

它做且只做三件事：

1. 按声明调用被测入口，把查询原样传进去
2. 按声明把返回值切成结构化条目
3. 报告诊断信息，让调用方判断这次解析是否可信

它不包含任何针对具体被测系统的逻辑——所有系统相关的信息都来自规格文件。
它也不修改被测系统的行为：不改写查询、不改参数、不补后处理。

用法：

    <被测系统的解释器> executor.py --spec spec.json --query "..." [--k 3]

规格文件（JSON）：

    {
      "workspace": "<被测工作区绝对路径，会加入 sys.path>",
      "pythonpath": ["<额外路径>"],
      "call": {
        "target": "<模块.属性，支持多层>",
        "args":   ["{query}"],              // {query} 与 {k} 会被替换
        "kwargs": {"language": "zh-CN"}
      },
      "result": {
        "select": "documents.0",            // 可选：先按点路径取出子值
        "kind": "text",                     // text | items
        "separator": "\\n\\n---\\n\\n",     // kind=text
        "score": {                          // 可选
          "pattern": "<正则，第一个捕获组为分数>",
          "placement": "prefix"             // prefix | suffix | anywhere
        },
        "trim": "none",                     // none | whitespace（显式声明才裁剪）
        "fields": {                         // kind=items
          "text": "text", "score": "score", "id": "id"
        }
      },
      "empty": { "equals": "<无结果时的返回值>" }
    }

输出为 JSON，字段见 build_report()。退出码：0 成功，1 规格错误，2 调用出错。
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import time
import traceback

QUERY_TOKEN = "{query}"
K_TOKEN = "{k}"

EXIT_OK = 0
EXIT_SPEC_ERROR = 1
EXIT_CALL_ERROR = 2


class SpecError(Exception):
    """规格本身不可用，与被测系统无关。"""


# --------------------------------------------------------------------------
# 调用
# --------------------------------------------------------------------------


def prepare_path(spec: dict) -> None:
    """把被测工作区与声明中的额外路径放到导入路径最前面。"""
    for extra in reversed(spec.get("pythonpath") or []):
        sys.path.insert(0, str(extra))
    workspace = spec.get("workspace")
    if workspace:
        sys.path.insert(0, str(workspace))


def resolve_target(dotted: str):
    """按 `模块.属性` 解析可调用对象，模块部分尝试最长匹配。"""
    parts = dotted.split(".")
    last_error: Exception | None = None
    for cut in range(len(parts) - 1, 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:cut]))
            for attr in parts[cut:]:
                obj = getattr(obj, attr)
        except (ImportError, AttributeError) as exc:
            # 既可能是该前缀不是模块，也可能是模块里没有这个属性
            last_error = exc
            continue
        return obj
    raise SpecError(f"无法导入 {dotted!r}：{last_error}")


def substituted(value, query: str, k: int):
    """替换参数模板里的占位符。

    整个字符串恰好是一个占位符时保留原类型（`{k}` 仍是整数），
    否则按文本插值。
    """
    if isinstance(value, str):
        if value == QUERY_TOKEN:
            return query
        if value == K_TOKEN:
            return k
        return value.replace(QUERY_TOKEN, query).replace(K_TOKEN, str(k))
    if isinstance(value, list):
        return [substituted(item, query, k) for item in value]
    if isinstance(value, dict):
        return {key: substituted(item, query, k) for key, item in value.items()}
    return value


def select_path(value, path: str | None):
    """按点路径取值，整数段视为列表下标。"""
    if not path:
        return value
    for segment in path.split("."):
        if isinstance(value, dict):
            value = value[segment]
        elif isinstance(value, (list, tuple)):
            value = value[int(segment)]
        else:
            raise SpecError(f"无法在 {type(value).__name__} 上取出 {segment!r}")
    return value


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------


def compile_score(score_config: dict | None):
    if not score_config:
        return None, "prefix"
    pattern = score_config.get("pattern")
    if not pattern:
        return None, "prefix"
    placement = score_config.get("placement") or "prefix"
    if placement not in ("prefix", "suffix", "anywhere"):
        raise SpecError(f"score.placement 取值非法：{placement!r}")
    return re.compile(pattern), placement


def apply_score(text: str, compiled, placement: str):
    """返回 (剩余正文, 分数, 分数原文)。只剥离声明过的分数片段。"""
    if compiled is None:
        return text, None, None

    if placement == "prefix":
        match = compiled.match(text)
        if match is None:
            return text, None, None
        remainder = text[match.end():]
    elif placement == "suffix":
        match = compiled.search(text)
        if match is None:
            return text, None, None
        remainder = text[: match.start()]
    else:  # anywhere
        match = compiled.search(text)
        if match is None:
            return text, None, None
        remainder = text[: match.start()] + text[match.end():]

    raw_score = match.group(1) if match.groups() else None
    try:
        score = float(raw_score) if raw_score is not None else None
    except (TypeError, ValueError):
        score = None
    return remainder, score, match.group(0)


def apply_trim(text, mode: str):
    """按声明裁剪正文的首尾空白。

    默认不裁剪：只剥离声明过的片段，其余逐字保留。需要裁剪时必须显式声明，
    且原始片段仍保存在 raw_fragment 中，不会被隐式丢弃。
    """
    if not isinstance(text, str):
        return text
    if mode == "whitespace":
        return text.strip()
    return text


def parse_text(raw, result_config: dict):
    if not isinstance(raw, str):
        raise SpecError(
            f"result.kind 声明为 text，但调用返回的是 {type(raw).__name__}"
        )

    separator = result_config.get("separator")
    fragments = raw.split(separator) if separator else [raw]
    compiled, placement = compile_score(result_config.get("score"))
    trim = result_config.get("trim", "none")

    items = []
    scored = 0
    for index, fragment in enumerate(fragments, start=1):
        text, score, score_raw = apply_score(fragment, compiled, placement)
        text = apply_trim(text, trim)
        if score is not None:
            scored += 1
        items.append(
            {
                "rank": index,
                "text": text,
                "score": score,
                "score_raw": score_raw,
                "id": None,
                # 逐字保留原始片段，供还原校验与事后审计
                "raw_fragment": fragment,
            }
        )

    diagnostics = {
        "item_count": len(items),
        "separator_found": (separator in raw) if separator else None,
        "score_parse_rate": (scored / len(items)) if items and compiled else None,
        "trim": trim,
        "reassemble_ok": None,
    }
    if separator is not None:
        diagnostics["reassemble_ok"] = separator.join(
            item["raw_fragment"] for item in items
        ) == raw
    else:
        diagnostics["reassemble_ok"] = len(items) == 1 and items[0]["raw_fragment"] == raw

    return items, diagnostics


def parse_items(raw, result_config: dict):
    if not isinstance(raw, (list, tuple)):
        raise SpecError(
            f"result.kind 声明为 items，但调用返回的是 {type(raw).__name__}"
        )

    fields = result_config.get("fields") or {}
    text_field = fields.get("text", "text")
    score_field = fields.get("score")
    id_field = fields.get("id")
    trim = result_config.get("trim", "none")

    items = []
    missing_text = 0
    scored = 0
    for index, element in enumerate(raw, start=1):
        if isinstance(element, dict):
            text = element.get(text_field)
            score = element.get(score_field) if score_field else None
            doc_id = element.get(id_field) if id_field else None
        else:
            # 元素本身就是文本
            text = element
            score = None
            doc_id = None

        if text is None:
            missing_text += 1
        text = apply_trim(text, trim)
        if score is not None:
            scored += 1

        items.append(
            {
                "rank": index,
                "text": text,
                "score": score,
                "score_raw": None,
                "id": doc_id,
                "raw_fragment": element,
            }
        )

    diagnostics = {
        "item_count": len(items),
        "separator_found": None,
        "score_parse_rate": (scored / len(items)) if items and score_field else None,
        "trim": trim,
        "reassemble_ok": len(items) == len(raw) and missing_text == 0,
        "missing_text_count": missing_text,
    }
    return items, diagnostics


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------


def json_safe(value, depth: int = 0):
    if depth > 6:
        return repr(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [json_safe(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item, depth + 1) for key, item in value.items()}
    return repr(value)


def validate_spec(spec: dict) -> None:
    call = spec.get("call")
    if not isinstance(call, dict) or not call.get("target"):
        raise SpecError("规格缺少 call.target")
    result = spec.get("result") or {}
    kind = result.get("kind", "text")
    if kind not in ("text", "items"):
        raise SpecError(f"result.kind 取值非法：{kind!r}")
    trim = result.get("trim", "none")
    if trim not in ("none", "whitespace"):
        raise SpecError(f"result.trim 取值非法：{trim!r}")


def build_report(spec: dict, query: str, k: int) -> dict:
    validate_spec(spec)
    prepare_path(spec)

    call = spec["call"]
    result_config = spec.get("result") or {}
    kind = result_config.get("kind", "text")
    empty_config = spec.get("empty") or {}

    target = resolve_target(call["target"])
    args = substituted(call.get("args") or [], query, k)
    kwargs = substituted(call.get("kwargs") or {}, query, k)

    started = time.perf_counter()
    try:
        returned = target(*args, **kwargs)
    except Exception as exc:  # 被测入口自己抛的异常，如实上报
        return {
            "ok": False,
            "error": {
                "stage": "call",
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
            "query_sent": query,
            "args_sent": json_safe(args),
            "kwargs_sent": json_safe(kwargs),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    raw = select_path(returned, result_config.get("select"))

    empty_matched = (
        "equals" in empty_config and raw == empty_config["equals"]
    )

    if empty_matched:
        items, diagnostics = [], {
            "item_count": 0,
            "separator_found": None,
            "score_parse_rate": None,
            "reassemble_ok": None,
            "empty_matched": True,
        }
    else:
        if kind == "text":
            items, diagnostics = parse_text(raw, result_config)
        else:
            items, diagnostics = parse_items(raw, result_config)
        diagnostics["empty_matched"] = False

    diagnostics["elapsed_ms"] = elapsed_ms

    return {
        "ok": True,
        "query_sent": query,
        "args_sent": json_safe(args),
        "kwargs_sent": json_safe(kwargs),
        "raw": json_safe(raw),
        "returned_type": type(returned).__name__,
        "items": items,
        "diagnostics": diagnostics,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="按声明调用被测入口并解析返回值。"
    )
    parser.add_argument("--spec", required=True, help="规格文件路径（JSON）")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--query", help="单条查询文本，原样传入")
    group.add_argument(
        "--queries",
        help="查询文件，每行一条；逐条执行并输出 JSONL。"
        "批量在同一个进程内完成，被测模型只加载一次",
    )
    parser.add_argument("--k", type=int, default=3, help="返回条数，替换 {k} 占位符")
    parser.add_argument(
        "--no-items-raw",
        action="store_true",
        help="省略每条目的 raw_fragment，减小体积",
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="省略顶层 raw 字段（items 与 diagnostics 保留）",
    )
    options = parser.parse_args(argv)

    try:
        with open(options.spec, encoding="utf-8") as handle:
            spec = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": {"stage": "spec", "message": str(exc)}}))
        return EXIT_SPEC_ERROR

    def trim_for_output(report: dict) -> None:
        if options.no_items_raw and report.get("items"):
            for item in report["items"]:
                item.pop("raw_fragment", None)
        if options.no_raw:
            report.pop("raw", None)

    if options.queries:
        try:
            with open(options.queries, encoding="utf-8") as handle:
                queries = [line.strip() for line in handle if line.strip()]
        except OSError as exc:
            print(json.dumps({"ok": False, "error": {"stage": "queries", "message": str(exc)}}))
            return EXIT_SPEC_ERROR

        failures = 0
        for query in queries:
            try:
                report = build_report(spec, query, options.k)
            except SpecError as exc:
                report = {"ok": False, "error": {"stage": "spec", "message": str(exc)},
                          "query_sent": query}
            if not report.get("ok"):
                failures += 1
            trim_for_output(report)
            print(json.dumps(report, ensure_ascii=False))
            sys.stdout.flush()
        return EXIT_CALL_ERROR if failures else EXIT_OK

    try:
        report = build_report(spec, options.query, options.k)
    except SpecError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"stage": "spec", "message": str(exc)}},
                ensure_ascii=False,
            )
        )
        return EXIT_SPEC_ERROR

    trim_for_output(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("ok"):
        return EXIT_CALL_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
