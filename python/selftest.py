#!/usr/bin/env python3
"""执行器的自测。

用**合成的**被测模块覆盖多种返回形状，验证执行器不依赖任何特定的向量库
或查询实现。任何依赖某个具体系统特性的写法都会在这里暴露。

只依赖标准库，可直接运行：

    python3 selftest.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import executor  # noqa: E402

EMPTY_MESSAGE = "没有找到相关内容。"

FAKE_MODULE = textwrap.dedent(
    '''
    """合成的被测模块。只用于验证执行器，不代表任何真实系统。"""

    EMPTY_MESSAGE = "没有找到相关内容。"
    DOCS = ["第一块正文", "第二块正文", "第三块正文"]


    def joined(query, k=3, use_rerank=False):
        if query == "__none__":
            return EMPTY_MESSAGE
        prefix = "[Rerank分数: {:.2f}]" if use_rerank else "[距离分数: {:.2f}]"
        blocks = [
            prefix.format(0.9 - index * 0.1) + "\\n" + DOCS[index]
            for index in range(min(k, len(DOCS)))
        ]
        return "\\n\\n---\\n\\n".join(blocks)


    def listed(query, k=3):
        if query == "__none__":
            return []
        return [
            {"text": DOCS[index], "score": 0.9 - index * 0.1, "doc_id": "d%d" % index}
            for index in range(min(k, len(DOCS)))
        ]


    def plain_strings(query, k=3):
        return DOCS[:k]


    def wrapped(query, k=3):
        return {"documents": [DOCS[:k]], "distances": [[0.1, 0.2, 0.3]]}


    def suffixed(query, k=3):
        return "\\n".join(
            DOCS[index] + " 【score={:.2f}】".format(0.9 - index * 0.1)
            for index in range(min(k, len(DOCS)))
        )


    def raises(query, k=3):
        raise RuntimeError("模拟的模型加载失败")


    def no_separator(query, k=3):
        return "整段文本没有任何分隔符"
    '''
).lstrip()


def build_spec(workspace: str, **overrides) -> dict:
    spec = {
        "workspace": workspace,
        "call": {"target": "fake_sut.joined", "args": ["{query}"], "kwargs": {"k": "{k}"}},
        "result": {"kind": "text", "separator": "\n\n---\n\n", "trim": "whitespace",
                   "score": {"pattern": r"\[(?:距离分数|Rerank分数):\s*([0-9.]+)\]",
                             "placement": "prefix"}},
        "empty": {"equals": EMPTY_MESSAGE},
    }
    for key, value in overrides.items():
        spec[key] = value
    return spec


def run(spec: dict, query: str, k: int = 3) -> dict:
    return executor.build_report(spec, query, k)


CASES: list[tuple[str, callable]] = []


def case(name):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


def make_cases(workspace: str):
    @case("拼接字符串 + 前缀分数 + 无结果哨兵")
    def _(_):
        report = run(build_spec(workspace), "任意查询")
        assert report["ok"], report
        items, diag = report["items"], report["diagnostics"]
        assert [item["text"] for item in items] == ["第一块正文", "第二块正文", "第三块正文"], items
        assert [item["score"] for item in items] == [0.9, 0.8, 0.7], items
        assert diag["score_parse_rate"] == 1.0, diag
        assert diag["separator_found"] is True, diag
        assert diag["reassemble_ok"] is True, diag
        assert diag["empty_matched"] is False, diag

    @case("无结果哨兵被识别，不产生条目")
    def _(_):
        report = run(build_spec(workspace), "__none__")
        assert report["ok"], report
        assert report["items"] == [], report["items"]
        assert report["diagnostics"]["empty_matched"] is True, report["diagnostics"]

    @case("已结构化的列表（字段映射）")
    def _(_):
        spec = build_spec(
            workspace,
            call={"target": "fake_sut.listed", "args": ["{query}"], "kwargs": {"k": "{k}"}},
            result={"kind": "items", "fields": {"text": "text", "score": "score", "id": "doc_id"}},
            empty=None,
        )
        spec.pop("empty", None)
        report = run(spec, "任意查询")
        assert report["ok"], report
        items = report["items"]
        assert [item["id"] for item in items] == ["d0", "d1", "d2"], items
        assert items[0]["score"] == 0.9, items
        assert report["diagnostics"]["reassemble_ok"] is True, report["diagnostics"]

    @case("列表元素是纯字符串")
    def _(_):
        spec = build_spec(
            workspace,
            call={"target": "fake_sut.plain_strings", "args": ["{query}"], "kwargs": {"k": "{k}"}},
            result={"kind": "items", "fields": {"text": "text"}},
        )
        spec.pop("empty", None)
        report = run(spec, "任意查询")
        assert [item["text"] for item in report["items"]] == ["第一块正文", "第二块正文", "第三块正文"], report["items"]

    @case("被字典包裹的返回值（select 取子值）")
    def _(_):
        spec = build_spec(
            workspace,
            call={"target": "fake_sut.wrapped", "args": ["{query}"], "kwargs": {"k": "{k}"}},
            result={"kind": "items", "select": "documents.0", "fields": {"text": "text"}},
        )
        spec.pop("empty", None)
        report = run(spec, "任意查询")
        assert report["ok"], report
        assert len(report["items"]) == 3, report["items"]

    @case("分数在后缀")
    def _(_):
        spec = build_spec(
            workspace,
            call={"target": "fake_sut.suffixed", "args": ["{query}"], "kwargs": {"k": "{k}"}},
            result={"kind": "text", "separator": "\n",
                    "score": {"pattern": r"【score=([0-9.]+)】", "placement": "suffix"}},
        )
        spec.pop("empty", None)
        report = run(spec, "任意查询")
        assert [item["score"] for item in report["items"]] == [0.9, 0.8, 0.7], report["items"]
        assert all("score=" not in item["text"] for item in report["items"]), report["items"]

    @case("入口抛异常：如实上报，不吞掉")
    def _(_):
        spec = build_spec(workspace, call={"target": "fake_sut.raises", "args": ["{query}"]})
        report = run(spec, "任意查询")
        assert report["ok"] is False, report
        assert report["error"]["stage"] == "call", report
        assert "模型加载失败" in report["error"]["message"], report

    @case("声明的分隔符不存在：条目数暴露问题")
    def _(_):
        spec = build_spec(
            workspace,
            call={"target": "fake_sut.no_separator", "args": ["{query}"]},
            result={"kind": "text", "separator": "\n\n---\n\n"},
        )
        spec.pop("empty", None)
        report = run(spec, "任意查询")
        assert report["diagnostics"]["separator_found"] is False, report["diagnostics"]
        assert report["diagnostics"]["item_count"] == 1, report["diagnostics"]

    @case("未声明 trim 时，正文逐字保留（不做隐式删改）")
    def _(_):
        spec = build_spec(workspace)
        spec["result"].pop("trim")
        report = run(spec, "任意查询")
        assert report["ok"], report
        assert report["items"][0]["text"] == "\n第一块正文", repr(report["items"][0]["text"])
        assert report["diagnostics"]["trim"] == "none", report["diagnostics"]
        # 即便正文带了未裁剪的换行，还原仍然逐字成立
        assert report["diagnostics"]["reassemble_ok"] is True, report["diagnostics"]

    @case("查询原样传入，不做任何改写")
    def _(_):
        spec = build_spec(workspace)
        report = run(spec, "  带空格 与标点！ ")
        assert report["query_sent"] == "  带空格 与标点！ ", report["query_sent"]
        assert report["args_sent"] == ["  带空格 与标点！ "], report["args_sent"]

    @case("规格错误被单独归类，不与被测报错混淆")
    def _(_):
        spec = build_spec(workspace, call={"target": "fake_sut.not_exist"})
        try:
            run(spec, "任意查询")
        except executor.SpecError:
            return
        raise AssertionError("应当抛出 SpecError")


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as workspace:
        with open(os.path.join(workspace, "fake_sut.py"), "w", encoding="utf-8") as handle:
            handle.write(FAKE_MODULE)

        make_cases(workspace)
        for name, fn in CASES:
            try:
                fn(workspace)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL  {name}\n      {type(exc).__name__}: {exc}")
            else:
                print(f"ok    {name}")

    print()
    print(f"{len(CASES) - failures}/{len(CASES)} 通过")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
