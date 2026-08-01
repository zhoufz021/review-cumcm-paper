# review-cumcm-paper

面向全国大学生数学建模竞赛（CUMCM）及类似数学建模论文的 Codex Skill。它以原始赛题为权威索引，使用可回查原文位置的证据、十二维评分、题型专项检查和修改复审，生成可直接用于论文修改的审核报告。

> 本工具用于论文修改与复审，不是官方竞赛评分器，也不预测获奖概率。

## 主要功能

- `quick`：快速检查可读性、摘要、结构、小问覆盖、图表、引用和明显缺漏；
- `full`：执行小问映射、四态证据判定、十二维评分、题型专项检查和完整报告生成；
- `re-review`：逐项判断上一轮问题是否已解决，并检查修改产生的新回归；
- 对 PDF、DOCX、Markdown 和纯文本建立可复用的页序/段落账本；
- 在材料不足时使用 `unverifiable` 降级，避免把不可核验内容误判为错误；
- 校验证据引用、权重、覆盖率、严重问题字段和非官方声明；
- 支持匿名审计、盲测运行时、双审核比较、人工黄金评估和修改前后成对门禁。

## 仓库结构

```text
.
├── review-cumcm-paper/       # 可安装的 Skill 目录
│   ├── SKILL.md
│   ├── agents/
│   ├── assets/
│   ├── references/
│   ├── scripts/
│   └── requirements.txt
├── docs/                     # 用户、开发和发布说明
├── examples/                 # 调用提示词示例
├── tests/                    # 不含真实论文的合成测试
├── tools/                    # 仓库验证与发布构建工具
├── .github/                  # CI、Issue 和 PR 模板
├── requirements.txt
└── LICENSE
```

原始优秀论文、普通论文、赛题附件、盲测管理员映射和人工审核结果均不包含在本仓库中。

## 环境要求

- Python 3.9 或更高版本；
- `pdfplumber`：PDF 文本抽取；
- `pypdf`：PDF 元数据净化和匿名审计。

安装依赖：

```bash
python -m pip install -r requirements.txt
```

如果只下载并解压 GitHub Release，则运行：

```bash
python -m pip install -r review-cumcm-paper/requirements.txt
```

## 安装 Skill

### 个人范围

将 `review-cumcm-paper` 整个目录复制到个人 Skill 目录：

```text
Windows: %USERPROFILE%\.agents\skills\review-cumcm-paper
macOS/Linux: ~/.agents/skills/review-cumcm-paper
```

### 项目范围

将目录复制到目标仓库：

```text
<repo>/.agents/skills/review-cumcm-paper
```

如果安装后没有出现，重新启动 Codex。

## 快速使用

安装后显式调用：

```text
$review-cumcm-paper

请按 full 模式全面审核附件中的论文。
竞赛：CUMCM 2024
题号：A
附件包括原始赛题、论文和赛题数据。
请输出带原文位置、问题等级、修改建议和完成性测试的报告。
```

全面审核至少需要：

1. 待审核论文；
2. 原始赛题；
3. 竞赛、年份和题号。

代码、数据、赛题附件、官方要求和上一轮审核报告属于可选输入。更多示例见 [docs/USAGE.md](docs/USAGE.md) 和 [examples/prompts.md](examples/prompts.md)。

## 输出内容

- 材料完整性、审核范围和整体置信度；
- 小问—模型—结果—验证矩阵；
- 十二个维度的状态、分数、理由和证据；
- 题型专项检查；
- 按严重程度排序的问题清单；
- 最优先修改的五项；
- 无法核验事项及待补材料；
- 修改复审检查表。

仅当已评分权重不少于适用权重的 80% 时才输出归一化总分。

## 本地验证

```bash
python tools/validate_repository.py
python -m unittest discover -s tests -v
```

CI 会在 Python 3.9 和 3.12 上执行相同检查。

## 构建发布包

```bash
python tools/build_release.py --version 1.0.0
```

生成物位于 `dist/`，包括 ZIP 和 `SHA256SUMS.txt`。ZIP 内含 Skill 的运行依赖清单。`dist/` 默认不纳入 Git，请将 ZIP 作为 GitHub Release 附件上传。

## 已知边界

- 旧式 `.doc` 需先转换为 PDF 或 DOCX；
- 扫描版 PDF 需要额外 OCR 或逐页视觉核验；
- 代码和数据缺失时只能降低相关结论的可核验性，不能据此判定实现错误；
- 当前校准样本不是两名人工审核者共同确认的最终黄金样本；
- 外部双人 4+4+4 盲测尚未完成，因此数值评分只用于修改排序。

## 贡献与安全

- 提交修改前阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；
- 安全问题请按 [SECURITY.md](SECURITY.md) 私下报告；
- 不要在 Issue、PR 或测试夹具中上传真实论文、队号、作者信息或未授权数据。

## 许可与第三方材料

本仓库当前采用保留所有权利的限制性许可，详见 [LICENSE](LICENSE)。若希望他人自由复制、修改和再分发，请由仓库所有者明确改用 MIT、Apache-2.0 等开源许可证。

第三方论文与赛事材料不随仓库分发。来源和非官方性质说明见 [NOTICE.md](NOTICE.md)。
