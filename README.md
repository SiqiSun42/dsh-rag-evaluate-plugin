# dsh-rag-evaluate

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)

评测工作区里已有的 RAG 检索系统。自动找出向量库和查询入口，生成评测集，跑出指标，指出问题出在哪一层、下一步该改什么。产物写在被测工作区的 `evaluation/` 下。

## 安装

需要先装好 DSH。

```sh
dsh plugin --profile web add <本仓库路径>
```

装完重启 DSH，再开一个新会话，skill 目录在会话启动时读取。

## 使用

在装有这个插件的工作区里输入以下指令：

```
帮我评测一下这个 RAG 系统
```

也可以显式调用 `/rag-evaluate`。

## 流程


| 步骤                                                      | 产物                                                   |
| --------------------------------------------------------- | ------------------------------------------------------ |
| ① 清点向量库与查询入口                                   | `rag-profile.json`                                     |
| ② 探测画像：运行环境、库的规模与内容质量、入口的可调用性 | 扩展`rag-profile.json`、接入层、`corpus-sample.jsonl`  |
| ③ 确认查询计划：方向与形态及各自比例                     | `query-plan.json`                                      |
| ④ 冻结规格：规模、判定标准、验收标准                     | `spec.json` / `spec.md`                                |
| ⑤ 打样：做几件样品交你确认                               | `corpus-source.jsonl`、`samples.jsonl`                 |
| ⑥ 全量生成评测集                                         | `eval-set.jsonl`                                       |
| ⑦ 执行与判定：批量检索、分片判定、聚合指标               | `raw-results.jsonl`、`judgments.jsonl`、`metrics.json` |
| ⑧ 效度校验：确认这次结果可信，不通过时指明退回哪一步     | `validation.json`                                      |
| ⑨ 归因分析：定位问题层级，给出建议                       | `report.md`                                            |

一次完整运行会在运行目录里留下这些：

```
evaluation/20260101-120000/
├── rag-profile.json  query-plan.json  spec.json  spec.md
├── adapter-spec.json
├── corpus-sample.jsonl  corpus-source.jsonl  samples.jsonl  eval-set.jsonl
├── raw-results.jsonl  judgments.jsonl  metrics.json
├── validation.json  report.md
└── 过程脚本（探针、分片、聚合、校验）
```

进度根据产物确定。对运行目录里面已经存在的文件，更换新会话也能无缝读取并且继续推进。重复运行不会覆盖已有产物；若想保留改前改后两版做对比，可以新建一次运行。

## 要求

- DSH
- 插件自身要 Python 3.10+（`mcp` 2.x 的要求），首次运行会自动建好 venv
- 被测系统的解释器 Python 3.9+ 即可，执行器只用标准库，跑在被测系统自己的解释器上
- 被测系统里得有向量库和查询入口

## 边界

只测指定的那个查询入口本身。项目里若还有查询改写、结果过滤、答案生成之类的环节，不在此列；报告里会提一句它们的存在，但不会测评。

库里是否存在某些具体信息也无法精确判断，需要外部信息。评测中若发现这类问题会向用户汇报，但属于检测项。

## 状态

第一版开发完成。

## 开发

执行器带一套合成自测，用多种人造返回形状验证执行器不依赖任何特定向量库：

```sh
python3 python/selftest.py
```

## 设计

架构、边界和每一步的设计依据见 [DESIGN.md](./DESIGN.md)。

## License

[MIT](./LICENSE)
