# 博客控制面板使用说明

这个控制面板是本地工具，只在你的电脑上运行，用来管理这个 Astro 静态博客。它不会给线上网站增加后台，也不需要服务器或数据库。

## 双击启动

在仓库根目录双击：

```text
open-blog-panel.bat
```

启动后会自动打开浏览器：

```text
http://127.0.0.1:8765/
```

也可以用命令启动：

```powershell
Set-Location D:\Blog
python .\scripts\blog_panel.py
```

## 换电脑后的首次使用

1. 安装 Git、Python 3、Node.js 22.12 或更新版本。
2. 从 GitHub 下载或 clone 这个仓库。
3. 双击 `open-blog-panel.bat`。
4. 在面板里点击“检查环境”。
5. 在面板里点击“安装/更新依赖”。
6. 点击“启动预览”，确认博客能在本机打开。

`node_modules/`、`site/dist/`、`.astro/` 这类本地生成文件不会上传到 GitHub。换电脑后用“安装/更新依赖”重新生成即可。

## 面板能做什么

- 检查环境：确认 Git、Node、npm 是否可用。
- 安装/更新依赖：在 `site/` 里执行 `npm ci` 或 `npm install`。
- 新建文章：自动生成 Markdown/MDX 文件和 frontmatter。
- 编辑已有文章：修改已发布文章或草稿的标题、摘要、标签、日期、封面、草稿状态和正文。
- 导航栏目：维护顶部导航，支持新增、删除、改名、改链接、显示/隐藏和排序。
- 网站视觉风格：从本地选择全站统一使用的主题，线上读者不能自行切换。
- 首页设计：修改首页文案、背景图、按钮和栏目显示状态。
- 给文章插入图片：上传图片并自动追加 Markdown 图片语法。
- 发布草稿：把 `draft: true` 改成 `draft: false`。
- 添加友链：写入 `site/src/data/friends.json`。
- 上传友链头像：把头像保存到仓库里的 `site/public/uploads/avatars/`。
- 删除友链：从 `friends.json` 移除对应链接。
- 启动预览：打开 Astro 本地预览服务。
- 停止预览：停止由面板启动的预览服务。
- 构建检查：运行 `npm run build`。
- 构建并推送：先构建，通过后再 `git add`、`git commit`、`git push`。

## 哪些应该上传 GitHub

这些都应该保留在仓库里，换电脑后才能继续用：

- `open-blog-panel.bat`
- `scripts/blog_panel.py`
- `scripts/update_blog.py`
- `docs/blog-control-panel.md`
- `site/src/data/friends.json`
- `site/src/data/home.json`
- `site/src/data/navigation.json`
- `site/src/content/blog/` 里的文章
- `site/public/uploads/` 里的上传图片
- `site/src/assets/` 里的图片
- `site/package.json` 和 `site/package-lock.json`

这些不要上传：

- `node_modules/`
- `site/dist/`
- `site/.astro/`
- `.env`、`.env.*`
- SSH 私钥、`.pem`、`.key`、`.p12`、`.pfx`

## 文章草稿

面板新建文章时默认保存为草稿：

```yaml
draft: true
```

草稿不会出现在首页、文章列表、标签、归档、搜索和 RSS 里。写完后在面板点击“发布这篇”即可公开。

草稿不是加密内容：如果仓库对外可见，草稿源码仍可能被看到。不要把密码、token、隐私信息或未授权内容写进草稿。

已发布文章也可以在面板里重新编辑。保存后本地 Markdown/MDX 文件会被更新，确认效果后再点击“构建并推送”。

## 图片

正文插图推荐使用面板里的“给文章插入图片”。它会把图片保存到：

```text
site/public/uploads/posts/
```

并自动在文章末尾追加：

```md
![图片说明](/uploads/posts/example.webp)
```

如果图片要放在正文中间，保存后打开“编辑已有文章”，把这行移动到合适的位置即可。

控制面板上传的首页背景图和正文插图支持 `jpg`、`jpeg`、`png`、`webp`、`avif`、`gif`，单个文件最多 12 MiB；为避免同源脚本风险，面板不接收 SVG 上传。文章封面图用于 Astro 图片优化，推荐使用 `webp` 或 `avif`，日常尽量控制在 1 MiB 内。

## 首页

首页配置保存在：

```text
site/src/data/home.json
```

日常建议直接用控制面板修改：可以改首页标题、说明、两个按钮、右侧信息、背景图，还可以打开或关闭“最近文章”“正在整理的主题”，并新增、隐藏或删除一个自定义首页栏目。

## 网站视觉风格

在控制面板的“网站视觉与字体”中选择风格并保存。这个设置保存在：

```text
site/src/data/theme.json
```

保存后刷新本地预览即可看到变化。线上网站不会给读者显示风格切换按钮；完成“构建并推送”后，所有读者会统一看到你最后发布的风格。

## 导航栏

顶部导航配置保存在：

```text
site/src/data/navigation.json
```

控制面板的“导航栏目”可以直接改截图里那排菜单：名称、链接、顺序、是否显示都能改，也可以新增或删除栏目。站内链接一般写成 `/blog`、`/tags` 这种路径，外部链接可以写完整的 `https://...`。

## 友链数据

友链保存在：

```text
site/src/data/friends.json
```

手工编辑时保持这种格式：

```json
[
  {
    "name": "朋友名字",
    "url": "https://example.com",
    "description": "一句话介绍",
    "avatar": "https://example.com/avatar.png"
  }
]
```

头像可以填远程链接，也可以在控制面板上传本地图片。推荐上传本地图片，避免对方网站头像改地址或加载失败。友链页已经设置兜底头像，加载失败时会显示 `/favicon.svg`。

## 本地预览

- 点击“启动预览”后，面板会等待 Astro 真正可以访问，再显示“运行中”；正常需要几秒钟。
- 默认预览地址是 `http://127.0.0.1:4321/`。如果 4321 已被其他程序占用，面板会自动选择后续空闲端口，并同步更新“打开预览”链接。
- 点击“停止预览”会关闭本次面板启动的整棵预览进程，不会关闭占用其他端口的外部程序。
- 如果启动失败，操作结果里会显示退出码和最近的 Astro 日志。先按提示处理，不需要反复双击控制面板。
- “启动预览”负责启动本地服务；“打开网站预览”负责在新窗口查看。面板首页也会直接嵌入已经就绪的网站。
- Windows 上控制面板只允许一个实例运行；已经打开时再次双击，会直接复用当前面板，避免按钮校验互相冲突。

## GitHub 登录

日常推送推荐使用 SSH key 或 Git Credential Manager。凭据由 Git 管理，不要把 token 写进仓库目录，也不要粘贴到文章、日志或控制面板源码里。换电脑后需要重新配置 GitHub 登录。

## 注意

- 控制面板只建议在本机打开，不要暴露到公网。
- “构建并推送”会真正提交并推送到远程仓库。
- Cloudflare Pages 会在 GitHub 收到 push 后自动部署。
- 发布前检查面板显示的文件清单；如果出现浏览器目录、几百个文件或陌生大文件，先停止操作。
- 完整维护、备份和回滚流程见 [maintenance.md](maintenance.md)。
