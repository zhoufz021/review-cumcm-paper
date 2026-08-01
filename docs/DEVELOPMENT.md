# 开发与验证

## 设计原则

- 原始赛题是小问数量的唯一权威来源；
- 搜索命中只提供候选位置，不能自动成为证据；
- 代码主要支持复现，不自动证明模型正确；
- 不适用和无法核验不得记为 0；
- 致命和重要问题必须能够回查原文；
- 盲测运行时不得携带样例结论。

## 安装开发环境

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 运行验证

```bash
python tools/validate_repository.py
python -m unittest discover -s tests -v
```

仓库验证器检查：

- Skill 必需目录和固定文件清单；
- 可安装 Skill 内的依赖清单及根目录转发文件；
- `SKILL.md` frontmatter、名称、行数和必要引用；
- 超过 100 行的参考文件是否包含目录；
- Markdown 本地链接；
- Python 语法和所有脚本的 `--help`；
- `agents/openai.yaml` 的界面字段；
- 本机绝对路径、秘密文件和不应入库的论文格式；
- GitHub Actions 是否固定到完整提交 SHA。

合成测试检查：

- 合法审核 JSON 能通过证据一致性门禁；
- 缺失维度的审核 JSON 会被拒绝；
- 合法审核 JSON 能生成报告；
- TXT 能被抽取，旧式 DOC 会被明确拒绝；
- PDF/DOCX 匿名净化、匿名审计和文本抽取；
- 盲测运行时、就绪门禁、12 对双审比较和人工黄金评估；
- 修改前后成对复审及发布构建对 Python 缓存的容错。

## 修改评分规则

1. 先在 `references/dimension-rubrics.md` 修改对应锚点；
2. 更新 `references/evidence-policy.md` 或题型规则；
3. 检查 `check-evidence-consistency.py` 是否需要同步；
4. 增加至少一个通过和一个拒绝测试；
5. 不在既有样本上反复调参后宣称前向验证；
6. 更新 Changelog。

## 发布

```bash
python tools/build_release.py --version 1.0.0
```

发布器会对 Skill 重新验证，并以固定时间戳和排序生成可复现 ZIP。将 `dist/*.zip` 和 `dist/SHA256SUMS.txt` 上传为同一个 GitHub Release 的附件。
