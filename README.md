# ztt-blog 项目说明

这是一个基于 Astro 的静态个人博客项目。仓库根目录负责项目管理、GitHub 推送和 Cloudflare Pages 部署辅助；真正的网站源码放在 `site/` 目录中；博客内容使用 Markdown/MDX 文件维护，构建时生成静态 HTML、图片资源、RSS 和站点地图。

## 快速使用

在 Windows 上，双击根目录的 `open-blog-panel.bat` 就能打开博客控制面板。面板会在本机启动，不需要服务器：

```text
http://127.0.0.1:8765/
```

换电脑后，先安装 Git、Python 3、Node.js 22.12 或更新版本，然后 clone 这个仓库，双击 `open-blog-panel.bat`，在面板里依次点击“检查环境”和“安装/更新依赖”。

控制面板、文章、图片、友链数据、启动器都会上传到 GitHub；密钥、本地依赖和构建缓存不会上传。详细说明见 `docs/blog-control-panel.md`。

## 一、整体架构

```text
D:\Blog
├─ README.md                     # 本项目总说明
├─ .gitignore                    # Git 忽略规则
├─ open-blog-panel.bat            # 双击打开本地博客控制面板
├─ docs/                         # 部署文档
├─ scripts/                      # 本地初始化、GitHub、SSH、推送、预览脚本
└─ site/                         # Astro 静态博客站点
   ├─ public/                    # 浏览器可直接访问的静态资源
   ├─ src/
   │  ├─ assets/                 # 由 Astro 管理和优化的图片资源
   │  ├─ components/             # 可复用页面组件
   │  ├─ content/                # Markdown/MDX 内容集合
   │  ├─ layouts/                # 页面布局模板
   │  ├─ pages/                  # 路由页面
   │  ├─ styles/                 # 全局样式
   │  ├─ consts.ts               # 站点标题和描述
   │  └─ content.config.ts       # 内容集合 schema
   ├─ astro.config.mjs           # Astro 配置
   ├─ package.json               # 前端依赖和 npm 命令
   ├─ package-lock.json          # 依赖锁定文件
   ├─ tsconfig.json              # TypeScript 配置
   └─ README.md                  # Astro 模板自带说明
```

项目采用“静态站点生成”架构：

1. 写作层：文章放在 `site/src/content/blog/`，每篇文章是 `.md` 或 `.mdx` 文件。
2. 内容校验层：`site/src/content.config.ts` 使用 Astro Content Collections 和 Zod 校验文章 frontmatter。
3. 页面路由层：`site/src/pages/` 根据文件名生成路由，例如首页 `/`、文章列表 `/blog/`、文章详情 `/blog/<slug>/`、RSS `/rss.xml`。
4. 组件层：`site/src/components/` 提供头部、底部、SEO、日期格式化、导航链接等复用组件。
5. 布局层：`site/src/layouts/BlogPost.astro` 统一文章页结构。
6. 样式层：`site/src/styles/global.css` 定义全站字体、颜色、排版、代码块和响应式规则。
7. 构建层：`npm run build` 由 Astro 生成 `site/dist/`，Cloudflare Pages 只需要托管这些静态文件。
8. 运维辅助层：`scripts/` 负责初始化项目、配置 GitHub、设置 SSH、提交更新、推送和本地预览。

## 二、运行方式

所有站点相关 npm 命令都在 `site/` 目录执行：

```powershell
Set-Location D:\Blog\site
npm install
npm run dev
```

生产构建：

```powershell
Set-Location D:\Blog\site
npm run build
```

本地预览构建结果：

```powershell
Set-Location D:\Blog\site
npm run preview
```

也可以使用根目录脚本：

```powershell
Set-Location D:\Blog
python .\scripts\preview_blog.py
python .\scripts\update_blog.py -m "update blog"
```

## 三、根目录文件功能

### `README.md`

项目总说明文件，说明目录结构、功能架构、运行方式、部署方式和优化建议。

### `.gitignore`

忽略不应该提交到 Git 的文件，例如：

- `node_modules/`：npm 依赖目录。
- `dist/`：构建输出目录。
- `.astro/`：Astro 本地缓存。
- `.wrangler/`：Cloudflare Wrangler 本地状态。
- `__pycache__/`、`*.pyc`：Python 缓存。
- `scripts/github_token.txt`：本地 GitHub token 文件，避免密钥误提交。
- `scripts/create_repo_and_push.log`：创建仓库失败时写入的错误日志。

### `docs/cloudflare-pages-deploy.md`

Cloudflare Pages 部署清单，记录：

- 仓库根目录是 `D:\Blog`
- Astro 站点目录是 `site`
- 构建命令是 `npm run build`
- 构建输出目录是 `dist`
- 自定义域名示例是 `www.200302.xyz`
- DNS 需要配置 CNAME 指向 Pages 项目域名

## 四、`site/` 站点目录

### `site/package.json`

定义 Astro 项目依赖和命令。

主要依赖：

- `astro`：静态站点框架。
- `@astrojs/mdx`：支持 `.mdx` 内容。
- `@astrojs/rss`：生成 RSS feed。
- `@astrojs/sitemap`：生成 sitemap。
- `sharp`：图片处理和优化。

主要命令：

- `npm run dev`：启动本地开发服务器。
- `npm run build`：构建生产静态文件。
- `npm run preview`：预览构建结果。
- `npm run astro`：调用 Astro CLI。

当前 `engines.node` 要求 `>=22.12.0`。

### `site/astro.config.mjs`

Astro 全局配置文件。

当前配置：

- 启用 MDX：`mdx()`
- 启用站点地图：`sitemap()`
- `site` 暂时设置为 `https://example.com`

注意：如果线上域名是 `https://www.200302.xyz`，建议把 `site` 改成真实域名，否则 canonical、RSS、sitemap、Open Graph 地址会生成到示例域名。

### `site/tsconfig.json`

TypeScript 配置文件，供 Astro 和编辑器识别类型。

### `site/package-lock.json`

锁定 npm 依赖版本，保证不同机器安装出来的依赖一致。

### `site/README.md`

Astro 博客模板自带说明。它不是当前项目的主说明，根目录 `README.md` 才是项目总文档。

## 五、`site/src/` 源码结构

### `site/src/consts.ts`

集中定义站点标题和站点描述：

- `SITE_TITLE`
- `SITE_DESCRIPTION`

这些值被首页、列表页、RSS、头部导航和 SEO 组件复用。

当前文件中的中文显示为乱码，建议后续统一修复为 UTF-8 编码下的正常中文。

### `site/src/content.config.ts`

定义 `blog` 内容集合。

它会从 `site/src/content/blog/` 加载所有 `.md` 和 `.mdx` 文件，并要求每篇文章 frontmatter 至少包含：

- `title`：文章标题，字符串。
- `description`：文章描述，字符串。
- `pubDate`：发布时间，会转换为 Date。
- `updatedDate`：可选更新时间。
- `heroImage`：可选封面图，使用 Astro 图片类型校验。

这个 schema 是内容质量的第一道保护。少写字段或字段类型不对时，构建阶段会报错。

### `site/src/styles/global.css`

全局样式文件，由 `BaseHead.astro` 引入后作用于所有页面。

主要内容：

- 定义主题色、灰度色、阴影变量。
- 加载 Atkinson 字体。
- 设置正文、标题、链接、段落、表格、图片、代码块、引用块样式。
- 设置移动端响应式字号和主内容间距。
- 提供 `.sr-only` 辅助类，用于无障碍隐藏文本。

## 六、页面路由

### `site/src/pages/index.astro`

首页，对应路由 `/`。

它引入：

- `BaseHead`
- `Header`
- `Footer`
- `SITE_TITLE`
- `SITE_DESCRIPTION`

页面主体目前是静态介绍内容。当前中文内容有明显乱码，建议优先修复。

### `site/src/pages/about.astro`

关于页，对应路由 `/about/`。

它使用 `BlogPost.astro` 布局，并传入：

- 标题
- 描述
- 发布时间
- 关于页封面图 `blog-placeholder-about.jpg`

页面内容目前也是静态段落，存在乱码问题。

### `site/src/pages/blog/index.astro`

博客列表页，对应路由 `/blog/`。

功能流程：

1. 使用 `getCollection('blog')` 读取所有文章。
2. 按 `pubDate` 从新到旧排序。
3. 生成文章卡片列表。
4. 如果文章配置了 `heroImage`，使用 Astro `Image` 组件输出优化后的封面图。
5. 每篇文章链接到 `/blog/<post.id>/`。

列表页中第一篇文章会被放大展示，其余文章两列排列，移动端改为单列。

### `site/src/pages/blog/[...slug].astro`

文章详情页，对应动态路由 `/blog/<slug>/`。

功能流程：

1. `getStaticPaths()` 读取 `blog` 集合中的所有文章。
2. 每篇文章生成一个静态路径。
3. `render(post)` 把 Markdown/MDX 内容渲染成 Astro 内容组件。
4. 使用 `BlogPost.astro` 统一输出文章页。

### `site/src/pages/rss.xml.js`

RSS 路由，对应 `/rss.xml`。

功能流程：

1. 读取所有博客文章。
2. 使用 `@astrojs/rss` 生成 RSS XML。
3. RSS 标题和描述来自 `SITE_TITLE`、`SITE_DESCRIPTION`。
4. 每篇文章链接到 `/blog/<post.id>/`。

## 七、布局和组件

### `site/src/layouts/BlogPost.astro`

文章页通用布局。

负责：

- 引入 `BaseHead` 输出 SEO 元信息。
- 引入 `Header` 和 `Footer`。
- 显示文章封面图。
- 显示发布时间和可选更新时间。
- 显示文章标题。
- 通过 `<slot />` 插入文章正文或关于页正文。

### `site/src/components/BaseHead.astro`

全站 `<head>` 元信息组件。

负责：

- 引入全局 CSS。
- 设置 charset、viewport、favicon。
- 预加载字体。
- 输出 canonical URL。
- 输出标题、描述。
- 输出 Open Graph 和 Twitter Card 元信息。
- 输出 RSS 和 sitemap 链接。

这是 SEO、社交分享预览、RSS 发现和全局样式的核心组件。

### `site/src/components/Header.astro`

全站头部导航。

负责：

- 显示站点标题。
- 提供内部导航：首页、博客、关于。
- 提供外部链接：个人站点、GitHub 仓库、线上站点。
- 移动端隐藏社交链接，保留核心导航。

当前导航文字出现乱码，需要修复为正常中文。

### `site/src/components/HeaderLink.astro`

导航链接组件。

根据当前路径判断链接是否处于激活状态，并给激活链接添加 `active` class。

### `site/src/components/Footer.astro`

全站页脚组件。

当前功能：

- 根据当前年份自动显示 `© <year> ztt. All rights reserved.`。
- 提供 3 个外链图标：个人站点、GitHub 仓库、Cloudflare Pages 线上站点。
- 使用 `.sr-only` 文本兼顾屏幕阅读器。
- 在页脚内定义自己的布局、颜色、hover 样式。

### `site/src/components/FormattedDate.astro`

日期格式化组件。

把文章中的 Date 对象格式化为页面可读日期，供文章列表和文章详情页复用。当前使用：

```ts
date.toLocaleDateString('en-us', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
})
```

所以页面日期会显示成英文月份格式，例如 `Mar 21, 2026`。如果站点主要面向中文读者，可以改为 `zh-CN`。

## 八、内容和资源

### `site/src/content/blog/`

博客文章目录。

当前文章文件：

- `first-post.md`
- `second-post.md`
- `third-post.md`
- `markdown-style-guide.md`
- `using-mdx.mdx`

文章内容现状：

- `first-post.md`：记录博客从本地初始化到 GitHub、Cloudflare Pages 上线的过程，但当前标题和描述显示为乱码。
- `second-post.md`：说明博客未来希望承载的内容，但当前标题和描述显示为乱码。
- `third-post.md`：说明本地预览、修改内容、提交和自动部署的更新流程，但当前标题和描述显示为乱码。
- `markdown-style-guide.md`：Astro 模板自带 Markdown 语法示例文章，英文内容正常。
- `using-mdx.mdx`：Astro 模板自带 MDX 示例文章，英文内容正常。

每篇文章应保持 frontmatter 符合 `content.config.ts` 中的 schema。推荐写法：

```md
---
title: "文章标题"
description: "文章摘要"
pubDate: "2026-03-21"
heroImage: "../../assets/blog-placeholder-1.jpg"
---

文章正文。
```

### `site/src/assets/`

Astro 管理的图片资源，主要用于文章封面和关于页封面。

当前文件：

- `blog-placeholder-1.jpg`
- `blog-placeholder-2.jpg`
- `blog-placeholder-3.jpg`
- `blog-placeholder-4.jpg`
- `blog-placeholder-5.jpg`
- `blog-placeholder-about.jpg`

这些图片经过 Astro `Image` 组件引用时可以参与构建期优化。

### `site/public/`

直接复制到最终站点根路径的静态资源。

当前文件：

- `favicon.svg`
- `favicon.ico`
- `fonts/atkinson-regular.woff`
- `fonts/atkinson-bold.woff`

这类资源不需要 import，页面中可以直接通过 `/favicon.svg`、`/fonts/...` 访问。

## 九、`scripts/` 脚本目录

### 配置文件

#### `scripts/blog_config.json`

本地脚本共用配置。

当前包含：

- GitHub owner：`zuofeng20000218-debug`
- 仓库名：`ztt-blog`
- 分支：`main`
- Git 用户名：`ztt`
- Git 邮箱：`ztt@users.noreply.github.com`

### 初始化和部署脚本

#### `scripts/bootstrap-blog.ps1`

PowerShell 初始化脚本。

功能：

- 检查 `git`、`node`、`npm`。
- 在 `site/` 不存在时用 Astro blog 模板创建项目。
- 生成 Cloudflare Pages 部署文档。
- 创建或补充 `.gitignore`。

#### `scripts/setup_blog.py`

综合管理脚本。

子命令包括：

- `check`：检查 Python、Git、Node、npm、gh、站点目录、依赖和 npm scripts。
- `git-init`：初始化 Git、设置身份、创建初始提交。
- `set-remote`：设置 GitHub 远程仓库，并可选推送。
- `build`：执行 `npm run build`。
- `cloudflare`：打印 Cloudflare Pages 配置项。
- `create-repo`：通过 GitHub API 创建仓库。
- `upload-secret`：上传 GitHub Actions secret，需要额外安装 `PyNaCl`。

这是目前功能最完整的自动化入口。

#### `scripts/create_repo_and_push.py`

通过 GitHub token 创建 `ztt-blog` 仓库并推送代码。

内部流程：

1. 把 `scripts/` 加入 `sys.path`，复用 `setup_blog.py` 中的函数。
2. 先从环境变量 `GITHUB_TOKEN` 读取 token。
3. 如果环境变量没有 token，再读取 `scripts/github_token.txt`。
4. 如果文件也没有，则通过隐藏输入提示手动输入 token。
5. 调用 `setup_blog.init_git()` 初始化 Git 并创建初始提交。
6. 调用 `setup_blog.create_repo()` 创建公开 GitHub 仓库、设置 origin、推送代码。
7. 如果执行失败，把完整异常写入 `scripts/create_repo_and_push.log`。

注意：`scripts/github_token.txt` 已经在 `.gitignore` 中，避免 token 被提交。

#### `scripts/push_to_existing_repo.py`

用于仓库已经在 GitHub 创建好的情况。

功能：

- 读取 `blog_config.json`。
- 处理 Git “dubious ownership” 安全目录问题。
- 确保 Git 仓库和分支存在。
- 设置 Git 用户身份。
- 执行 `git add .`，有改动时用 `"Initial blog scaffold"` 创建提交。
- 设置 `origin` 并推送到 GitHub。

它适合“GitHub 仓库已经手动创建好，只需要把本地项目推上去”的场景。

#### `scripts/update_blog.py`

日常更新脚本。

功能：

- 检查 Git 工作区是否有改动。
- 自动 `git add .`。
- 创建提交。
- 默认推送到远程仓库。
- 可用 `--no-push` 只提交不推送。

它不会先运行 `npm run build`，所以如果要保证提交前一定能构建通过，需要手动先在 `site/` 目录执行构建，或后续增强这个脚本。

#### `scripts/preview_blog.py`

本地预览脚本。

它检查 `npm` 是否存在，然后进入 `site/` 执行：

```powershell
npm run dev
```

也就是说它启动的是 Astro 开发服务器，不是 `npm run preview`。适合日常写文章或改页面时快速打开本地开发环境。

### GitHub 页面和连通性脚本

#### `scripts/open_github_token.py`

打开 GitHub fine-grained personal access token 创建页面。

实际打开地址：

```text
https://github.com/settings/personal-access-tokens/new
```

#### `scripts/open_github_new_repo.py`

打开 GitHub 新建仓库页面，并提示创建空仓库。

实际打开地址：

```text
https://github.com/new
```

脚本会提示仓库名使用 `ztt-blog`，并提醒不要勾选 README、`.gitignore`、license，保持远程仓库为空。

#### `scripts/test_github_connectivity.py`

检查当前机器到 GitHub 的连通性，包括 DNS、HTTPS 和 Git 访问。

具体检查：

- `github.com` 的 DNS 解析。
- `https://github.com` 的 HTTPS 访问。
- `https://api.github.com` 的 HTTPS 访问。
- `https://github.com/zuofeng20000218-debug/ztt-blog.git` 的 `git ls-remote`。

### SSH 相关脚本

#### `scripts/setup_ssh_for_github.py`

生成专用于此博客的 GitHub SSH key，并打印公钥，方便复制到 GitHub SSH keys 页面。

具体行为：

- 读取 `blog_config.json` 中的 `git_email` 作为 SSH key 注释。
- 确保用户主目录下的 `.ssh` 目录存在。
- 如果 `~/.ssh/id_ed25519_github_ztt_blog` 不存在，执行 `ssh-keygen -t ed25519` 生成无密码 key。
- 如果公钥文件存在，打印公钥内容和保存路径。

#### `scripts/open_github_ssh_keys.py`

打开 GitHub SSH keys 设置页面。

实际打开地址：

```text
https://github.com/settings/keys
```

#### `scripts/configure_github_ssh.py`

写入 SSH config，让 `github.com` 使用博客专用 SSH key。

它会向 `~/.ssh/config` 追加以下类型的配置块：

```text
Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519_github_ztt_blog
  IdentitiesOnly yes
```

如果配置里已经有这个 key，就不会重复追加。

#### `scripts/trust_github_host.py`

获取 GitHub SSH host keys 并追加到本机 `known_hosts`。

具体行为：

- 确保 `~/.ssh` 存在。
- 如果 `known_hosts` 里已经包含 `github.com`，直接退出。
- 否则执行 `ssh-keyscan github.com`。
- 把扫描到的 host key 追加到 `~/.ssh/known_hosts`。

#### `scripts/test_github_ssh.py`

测试当前 SSH 配置能否连接 GitHub。

实际执行：

```powershell
ssh -T git@github.com
```

GitHub 的 SSH 测试成功时也可能返回非 0 状态码，判断时应主要看输出信息。

#### `scripts/push_via_ssh.py`

把 Git remote 切换为 SSH 地址，并推送 `main` 分支。

具体行为：

- 读取 `blog_config.json` 中的 `github_owner`、`github_repo`、`git_branch`。
- 拼出 `git@github.com:<owner>/<repo>.git`。
- 如果 origin 不存在则添加，存在但不同则更新。
- 执行 `git push -u origin <branch>`。

## 十、部署架构

当前推荐部署链路：

```text
本地写文章/改代码
        ↓
npm run build
        ↓
Git commit
        ↓
Push 到 GitHub main
        ↓
Cloudflare Pages 自动拉取仓库
        ↓
执行 npm run build
        ↓
发布 site/dist 静态文件
        ↓
用户访问 www.200302.xyz
```

这个架构的优点：

- 不需要自建服务器。
- 静态页面访问速度快。
- Cloudflare Pages 可免费托管静态站点。
- GitHub 保存源码和文章历史。
- Markdown/MDX 写文章简单，适合个人博客。
- Astro 默认输出静态 HTML，性能和 SEO 友好。

## 十一、当前存在的问题

### 1. 多个中文文件内容乱码

目前以下文件读取时出现明显乱码：

- `site/src/consts.ts`
- `site/src/pages/index.astro`
- `site/src/pages/about.astro`
- `site/src/components/Header.astro`
- `site/README.md`
- 根目录旧版 `README.md` 中的部分 token 示例文字

这通常是文件编码、终端编码或历史写入方式不一致导致的。建议统一为 UTF-8，并手动恢复站点标题、导航文字、首页文案和关于页文案。

### 2. `astro.config.mjs` 的 `site` 仍是示例域名

当前为：

```js
site: 'https://example.com'
```

建议改为真实站点：

```js
site: 'https://www.200302.xyz'
```

否则 sitemap、RSS、canonical URL 和社交分享链接会不准确。

### 3. 首页和关于页内容仍像模板占位

页面结构已经可用，但正文内容需要替换成真实个人介绍、博客定位、联系方式或文章导读。

### 4. 导航链接文本需要修复

`Header.astro` 中首页、博客、关于文字现在乱码。建议统一为：

- 首页
- 博客
- 关于

### 5. 部分脚本功能重叠

`setup_blog.py`、`create_repo_and_push.py`、`push_to_existing_repo.py`、`push_via_ssh.py` 都涉及仓库初始化和推送。它们有各自适用场景，但后续维护成本较高。

## 十二、无需新增服务器成本的优化建议

### 优先级 A：马上值得做

1. 修复乱码并统一 UTF-8 编码。
   - 先修 `consts.ts`、`Header.astro`、`index.astro`、`about.astro`。
   - 保证编辑器保存编码为 UTF-8。
   - PowerShell 中必要时使用 `chcp 65001` 或配置终端 UTF-8。

2. 修改 `site/astro.config.mjs` 的 `site` 为真实域名。
   - 这会直接改善 RSS、sitemap、canonical 和分享预览。

3. 给 `package.json` 增加检查命令。
   - 可以加入 `astro check`，部署前发现类型和内容 schema 问题。
   - 不需要新服务器，只是本地和 CI 构建前多一步检查。

4. 清理模板内容。
   - 删除或改写 `site/README.md` 中的模板乱码说明。
   - 把示例文章逐步替换成真实文章。

### 优先级 B：提升可维护性

1. 合并脚本入口。
   - 保留 `setup_blog.py` 作为主入口。
   - 其他脚本可以逐步改为“薄封装”或在 README 中标注使用场景。
   - 这样以后不会出现多个脚本逻辑不一致。

2. 增加文章写作规范。
   - 在 README 或 `docs/` 中写明 frontmatter 模板。
   - 约定图片尺寸、标题长度、描述长度、发布日期格式。

3. 把站点信息集中配置。
   - 现在站点标题在 `consts.ts`，部署域名在 `astro.config.mjs`，GitHub 信息在 `blog_config.json`。
   - 可以保留现状，但建议在 README 中明确“改标题去哪里，改域名去哪里，改仓库去哪里”。

4. 改善文章列表体验。
   - 增加文章摘要 `description`。
   - 增加标签或分类字段。
   - 增加归档页。
   - 这些都可以纯静态生成，不需要后端。

### 优先级 C：提升 SEO 和访问体验

1. 给文章页 `BaseHead` 传入文章封面图。
   - 当前 `BlogPost.astro` 只传了标题和描述，`BaseHead` 会使用默认图。
   - 建议把文章 `heroImage` 也传给 `BaseHead`，让社交分享显示文章自己的封面。

2. RSS 文章排序。
   - 当前 RSS 读取文章后直接输出。
   - 建议和博客列表一样按发布时间倒序排列。

3. 优化图片 alt 文本。
   - 目前封面图 `alt=""`。
   - 如果图片有内容意义，建议使用文章标题或单独的图片描述。

4. 增加 404 页面。
   - 在 `site/src/pages/404.astro` 添加自定义 404。
   - Astro 和 Cloudflare Pages 都支持静态 404，不需要服务器。

5. 增加站内搜索的静态实现。
   - 可以构建时生成 JSON 索引，在浏览器端搜索。
   - 不需要数据库或服务器。

### 优先级 D：自动化但不增加成本

1. 使用 GitHub Actions 做构建检查。
   - 每次 push 前或 pull request 时执行 `npm ci`、`npm run build`。
   - GitHub Actions 对个人项目通常已有免费额度。

2. 使用 Cloudflare Pages 自动部署。
   - 继续让 Cloudflare Pages 监听 GitHub `main` 分支。
   - 不需要手动上传 `dist/`。

3. 加一个日常发布脚本规范。
   - 推荐日常只使用：

```powershell
Set-Location D:\Blog
python .\scripts\update_blog.py -m "写清楚这次更新内容"
```

4. 在本地提交前先构建。
   - 可以让 `update_blog.py` 在提交前可选执行 `npm run build`。
   - 这样能提前发现 Markdown frontmatter 或 Astro 编译问题。

## 十三、推荐维护流程

### 新增文章

1. 在 `site/src/content/blog/` 新建 `.md` 或 `.mdx` 文件。
2. 按 `content.config.ts` 写好 frontmatter。
3. 如需封面，把图片放入 `site/src/assets/`。
4. 本地运行：

```powershell
Set-Location D:\Blog\site
npm run dev
```

5. 确认页面正常后构建：

```powershell
npm run build
```

6. 提交并推送：

```powershell
Set-Location D:\Blog
python .\scripts\update_blog.py -m "add new blog post"
```

### 修改站点标题和描述

编辑：

```text
site/src/consts.ts
```

### 修改域名

编辑：

```text
site/astro.config.mjs
docs/cloudflare-pages-deploy.md
```

### 修改导航

编辑：

```text
site/src/components/Header.astro
```

### 修改文章页样式

编辑：

```text
site/src/layouts/BlogPost.astro
site/src/styles/global.css
```

### 修改博客列表样式

编辑：

```text
site/src/pages/blog/index.astro
```

## 十四、总结

这个项目的核心是一个低成本、易部署、适合个人长期维护的静态博客：

- Astro 负责生成静态站点。
- Markdown/MDX 负责写文章。
- GitHub 负责版本管理。
- Cloudflare Pages 负责免费静态托管和自动部署。
- `scripts/` 负责降低初始化、推送和 SSH 配置的操作成本。

后续最值得优先处理的是：修复乱码、设置真实 `site` 域名、替换模板内容、补充构建检查。这些都不需要购买服务器，也不会改变现有部署架构。
