# Cloudflare Pages 部署说明

这个博客是静态站点，Cloudflare Pages 只需要从 GitHub 拉取仓库并构建 `site/` 目录。

## Pages 配置

- 生产分支：`main`
- 根目录：`site`
- 构建命令：`npm run build`
- 输出目录：`dist`
- 生产域名：`https://www.200302.xyz`

## 本地发布流程

推荐用控制面板完成发布：

1. 双击仓库根目录的 `open-blog-panel.bat`。
2. 点击“构建检查”。
3. 确认没问题后点击“构建并推送”。
4. Cloudflare Pages 会在 GitHub 收到 push 后自动构建并部署。

命令行方式：

```powershell
Set-Location D:\Blog
python .\scripts\update_blog.py -m "update blog"
```

## 自定义域名

在 Cloudflare Pages 项目的 Custom domains 中添加：

```text
www.200302.xyz
```

DNS 记录通常是：

```text
Type:   CNAME
Name:   www
Target: <your-pages-project>.pages.dev
```

先在 Cloudflare Pages 里添加自定义域名，再按 Cloudflare 给出的目标配置 DNS。

## 发布失败或回滚

- 构建失败时先看 Cloudflare 日志中的第一条实际错误，本次失败不会替换上一份成功部署。
- 线上内容有误时，可先在 Cloudflare Pages 的部署记录中回退到上一份成功版本。
- 仓库仍要随后修正：文章问题可改回 `draft: true`；代码问题使用 `git revert <提交编号>`，再正常推送。
- 不要用 `git reset --hard` 或强制推送处理普通发布问题。

完整检查清单见 [博客日常维护规则](maintenance.md)。
