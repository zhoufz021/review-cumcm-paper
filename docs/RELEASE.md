# 发布检查表

## 发布前

- [ ] `SKILL.md` 名称、描述和中文说明准确；
- [ ] `agents/openai.yaml` 与 `SKILL.md` 一致；
- [ ] `review-cumcm-paper/requirements.txt` 随 Skill 分发，根目录依赖文件只转发到它；
- [ ] 所有引用和脚本入口可用；
- [ ] `python tools/validate_repository.py` 通过；
- [ ] `python -m unittest discover -s tests -v` 通过；
- [ ] 没有论文、数据、队号、作者、管理员映射或人工黄金文件；
- [ ] `requirements.txt` 覆盖所有第三方运行依赖；
- [ ] Changelog 已更新；
- [ ] 版本号已确定；
- [ ] `LICENSE` 已填写真实版权主体，且许可选择已由仓库所有者确认；
- [ ] `reviewed-exemplars.md` 的派生描述、样本名称和来源标注已完成公开发布权利复核。

## 构建

```bash
python tools/build_release.py --version 1.0.0
```

确认：

- [ ] ZIP 根目录为 `review-cumcm-paper/`；
- [ ] ZIP 仅包含固定的 22 个 Skill 文件；
- [ ] ZIP 含 `review-cumcm-paper/requirements.txt`；
- [ ] ZIP 不含 `__pycache__`、测试、论文或仓库文档；
- [ ] `SHA256SUMS.txt` 与 ZIP 实际哈希一致；
- [ ] 连续构建两次得到相同哈希。

## GitHub Release

1. 创建与版本一致的标签，例如 `v1.0.0`；
2. 从 Changelog 填写 Release Notes；
3. 上传 ZIP 和 `SHA256SUMS.txt`；
4. 发布后重新下载并核对 SHA-256；
5. 在干净环境中解压，安装 ZIP 内的依赖清单，并确认所有脚本的 `--help` 可运行；
6. 将解压后的 `review-cumcm-paper/` 安装到 Codex，执行一次合成材料烟雾审核。

## 发布后

- [ ] README 的安装路径仍正确；
- [ ] CI 在主分支和标签上通过；
- [ ] Release 附件可下载；
- [ ] 没有误上传被 `.gitignore` 排除的私人材料；
- [ ] 已启用 Private vulnerability reporting，或在 `SECURITY.md` 提供可用的私密联系方式。
