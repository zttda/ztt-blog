# 博客仓库协作规则

## 沟通

- 默认用中文解释，把使用者当作没有工程经验的新手；先理解目标，再纠正可能有风险或不准确的指令。
- 当用户说“Claude交流”“问 Claude”“让 Claude 看看”“把这个发给 Claude”等请求时，优先使用 `$shared-claude-bridge`。默认使用当前目录、保留记录并继续当前 Claude 会话。
- 不在没有明确授权时执行 `git push`、强制推送、历史重写或删除已发布内容。

## 文件边界

- 网站代码在 `site/`，文章在 `site/src/content/blog/`，本地管理工具在 `scripts/`。
- 不提交 `node_modules/`、`dist/`、`.astro/`、`.tmp-*`、浏览器配置、设计候选图、密钥或 token。
- 正式图片只保留实际被页面或文章引用的版本。正文图优先 WebP/AVIF，建议单张不超过 1 MiB。
- 不直接编辑构建产物；修改源码后重新构建。

## 内容规则

- 新文章必须默认 `draft: true`。发布前补齐标题、摘要、日期、图片说明和 1-5 个稳定标签。
- `draft: true` 只是不在网站展示；文件仍可能进入 GitHub，不能写密码、身份证号、私人聊天或未授权内容。
- 修改已发布文章时填写 `updatedDate`。删除或大幅改写已发布内容前先说明影响。

## 修改与发布

1. 开始前查看 `git status`，不要覆盖现有未提交修改。
2. 改动保持聚焦，不顺手重构无关代码。
3. 发布前运行 `python -B -m unittest discover -s scripts/tests -p "test_*.py"` 和 `npm run build`（目录 `site/`）。
4. 检查变更清单，确认没有缓存、大文件或敏感文件。
5. 提交说明写清目的，例如 `post: 发布《标题》`、`site: 修复移动端导航`、`ops: 补充发布检查`。

详细日常流程见 `docs/maintenance.md`。
