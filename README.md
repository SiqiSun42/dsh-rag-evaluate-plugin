# dsh-rag-evaluate

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Status](https://img.shields.io/badge/status-early%20development-orange.svg)

运行在 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 上的 RAG 系统评测插件。

给它一个工作区，它会发现里面的向量库与查询入口，构建评测集，跑出指标，并指出问题出在哪一层、下一步该改什么。

> **它对被测系统只做一件事：新增一个保存评测内容的文件夹。**
> 不改动 RAG 代码，也不改向量库——要改是评测结束之后的事。

## 它解决什么问题

RAG 效果不好时，问题可能出在好几个地方：语料解析、切分、embedding、召回、重排、阈值。凭感觉改一处，往往既不知道有没有变好，也不知道是不是改错了地方。

这个插件把评测拆成九步，先把数据做扎实，再按固定清单逐层诊断——**结论挂得上数字，建议指得出是哪一层的失败案例**。

## 九步流程

| 步骤 | 做什么 | 主要产物 |
|---|---|---|
| ① | 清点：确认向量库与查询入口是否存在，整理候选链路 | `rag-profile.json` |
| ② | 探测画像：运行环境、向量库的规模与质量缺陷、入口的可调用性 | 接入层、`corpus-sample.jsonl` |
| ③ | 确认查询计划：方向与形态及其比例 | `query-plan.json` |
| ④ | 冻结规格：规模、判定标准、验收标准，固化为带版本的规格 | `spec.json` / `spec.md` |
| ⑤ | 打样：做几件样品交用户确认 | `corpus-source.jsonl`、`samples.jsonl` |
| ⑥ | 全量生成：按规格覆盖全部方向与形态 | `eval-set.jsonl` |
| ⑦ | 执行与判定：批量检索、分片判定、聚合指标 | `raw-results.jsonl`、`judgments.jsonl`、`metrics.json` |
| ⑧ | 效度校验：确认本次运行结果可信，不通过时指明退回哪一步 | `validation.json` |
| ⑨ | 归因分析：定位问题层级，给出建议 | `report.md` |

每一步都有用户确认的门槛。**随时可以退回前面的步骤重做**——回退后受影响的下游会重走一遍。

## 安装

需要先装好 DSH。

```sh
dsh plugin --profile web add <本仓库路径>
```

首次运行会自动创建 Python 环境并安装依赖。

装完重启 DSH，然后**新开一个会话**（会话启动时才会读取 skill 目录）。

## 使用

在装有该插件的工作区里，直接对 Agent 说：

```
帮我评测一下这个 RAG 系统
```

也可以显式调用：

```
/rag-evaluate
```

之后 Agent 会按九步推进，每一步做完向你汇报、等你确认。

## 它不做什么

- **不改写查询**，也不调整被测系统的任何参数、阈值或后处理
- **不修改**被测项目的文件，也不动向量库
- **不把上游改写与下游后处理算进来。** 如果被测项目里还有查询改写、结果过滤、答案生成之类的环节，插件当作它们不存在——只测你指定的那个查询入口本身。报告里可能提一句「项目里已经有某个环节，可以考虑往那个方向调整」，但那是建议，**插件不改也不测**
- **不检测某个内容是否在向量库里。** 判断「库里缺什么」需要知道库里**应该**有什么，那是外部信息，插件无从得知，库的内容该由别的工具去查。评测中若撞上这类问题，报告里可能提一句——**那属于顺带发现，不是本插件的检测项**

## 产物

全部写在被测工作区的 `evaluation/<运行标识>/` 下，不散落到别处：

```
evaluation/20260919-110556/
├── 画像与规格     rag-profile.json  query-plan.json  spec.json  spec.md
├── 语料与评测集   corpus-sample.jsonl  corpus-source.jsonl  samples.jsonl  eval-set.jsonl
├── 接入层         adapter-spec.json
├── 执行与判定     raw-results.jsonl  judgments.jsonl  metrics.json
├── 校验与报告     validation.json  report.md
└── 过程脚本       探针、分片、聚合脚本
```

进度由产物决定而非记忆：看一眼运行目录里已有哪些文件，就知道走到了哪一步，换个会话也能接着上次继续。

再次运行**不会覆盖**既有产物。想保留两版做对比（改前 / 改后），新建一次运行。

## 要求

- DSH
- **Python 3.10+**——插件自身的运行环境（`mcp` 2.x 的要求），首次运行自动创建
- 被测系统的解释器 **Python 3.9+** 即可——执行器只用标准库，跑在被测系统自己的解释器上
- 被测系统需要包含一个**向量库**和一个**查询入口**

## 当前状态

早期开发中，接口与产物格式仍可能变化。

九步的 skill 已全部写完。第①～⑦步已对真实系统实测跑通；第⑧⑨步跑通过一轮，但那之后 skill 改过（报告结构、验收标准），新版待重新实测。

## 开发

执行器带一套合成自测，用多种人造返回形状验证它不依赖任何特定向量库：

```sh
python3 python/selftest.py
```

## 设计

架构、边界、每一步的设计依据与被否决的方案，见 [DESIGN.md](./DESIGN.md)。

## License

[MIT](./LICENSE)
