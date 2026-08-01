# 贡献指南

感谢改进 `review-cumcm-paper`。本项目最重视证据可回查、输入降级真实、盲测隔离和不虚构结论。

## 开始之前

1. 先用 Issue 描述问题、使用场景和预期行为；
2. 不要上传真实参赛论文、作者信息、队号、未授权赛题附件或管理员盲测材料；
3. 不要把校准候选分数描述为官方成绩或人工金标准；
4. 修改评分规则时，说明受影响的维度、证据状态和回归样例。

## 本地开发

```bash
python -m pip install -r requirements.txt
python tools/validate_repository.py
python -m unittest discover -s tests -v
```

## 修改要求

- `SKILL.md` 只保留核心工作流，并保持少于 500 行；
- 详细规则放入 `references/`，输出模板放入 `assets/`；
- 所有新增脚本必须提供 `--help`，并使用非零退出码表示拒绝或错误；
- 新增 Markdown 链接必须能够在仓库内解析；
- 新增依赖必须写入 `requirements.txt`；
- 不得在代码、测试或文档中写入本机绝对路径；
- 不得降低四态证据、80% 总分覆盖和重要意见位置门禁；
- 修改正式 Skill 后重新构建发行 ZIP，不要手工编辑 ZIP 内容。

## 提交信息

推荐使用清晰的祈使句，例如：

```text
Add OCR degradation guidance
Tighten evidence-location validation
Fix DOCX metadata sanitization
```

## Pull Request 检查表

- [ ] 变更范围单一且说明充分；
- [ ] 本地验证通过；
- [ ] 没有真实论文、身份信息或密钥；
- [ ] 文档、脚本、模板和元数据保持一致；
- [ ] 新行为包含正向和拒绝测试；
- [ ] 没有把内部量表描述为官方评分。
