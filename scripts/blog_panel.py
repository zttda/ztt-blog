#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import deque
import html
import json
import mimetypes
import os
import re
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse


ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"
POSTS_DIR = SITE_DIR / "src" / "content" / "blog"
POST_TEMPLATES_DIR = ROOT / "scripts" / "post_templates"
FRIENDS_FILE = SITE_DIR / "src" / "data" / "friends.json"
ASSETS_DIR = SITE_DIR / "src" / "assets"
PREVIEW_HOST = "127.0.0.1"
PREVIEW_PORT = 4321
PREVIEW_PORT_ATTEMPTS = 20
PREVIEW_START_TIMEOUT_SECONDS = 15.0
PANEL_HOST = "127.0.0.1"
PANEL_PORT = 8765
MAX_REQUEST_BYTES = 32 * 1024 * 1024
CSRF_TOKEN = secrets.token_urlsafe(32)

preview_process: subprocess.Popen[str] | None = None
active_preview_port = PREVIEW_PORT
preview_output: deque[str] = deque(maxlen=120)
preview_output_thread: threading.Thread | None = None
preview_output_lock = threading.Lock()
preview_lock = threading.Lock()


def is_trusted_host(host_header: str, port: int) -> bool:
    try:
        parsed = urlparse(f"http://{host_header}")
        return parsed.hostname in {PANEL_HOST, "localhost"} and parsed.port == port
    except ValueError:
        return False


def is_trusted_origin(origin: str, host_header: str) -> bool:
    if not origin:
        return True
    try:
        parsed_origin = urlparse(origin)
        parsed_host = urlparse(f"http://{host_header}")
        return (
            parsed_origin.scheme == "http"
            and parsed_origin.hostname == parsed_host.hostname
            and parsed_origin.port == parsed_host.port
        )
    except ValueError:
        return False


def inject_csrf_fields(content: str) -> str:
    field = f'<input type="hidden" name="_csrf" value="{CSRF_TOKEN}">'
    post_form = re.compile(r'(<form\b(?=[^>]*\bmethod=["\']post["\'])[^>]*>)', re.IGNORECASE)
    return post_form.sub(lambda match: match.group(1) + field, content)


@dataclass
class CommandResult:
    code: int
    output: str


@dataclass
class UploadedFile:
    filename: str
    content_type: str
    data: bytes


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg"}
UPLOAD_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS - {".svg"}
COVER_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
FONT_EXTENSIONS = {".woff2", ".woff", ".ttf", ".otf"}
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_UPLOAD_FILES = 12
POST_EXTENSIONS = {".md", ".mdx"}
EDITABLE_EXTENSIONS = {
    ".astro",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mdx",
    ".mjs",
    ".ps1",
    ".py",
    ".svg",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
EDIT_EXCLUDED_PARTS = {
    ".git",
    ".astro",
    ".wrangler",
    ".tmp-edge-screens",
    "__pycache__",
    "design-previews",
    "dist",
    "image-candidates",
    "node_modules",
}
EDIT_EXCLUDED_NAMES = {"github_token.txt"}
HOME_FILE = SITE_DIR / "src" / "data" / "home.json"
NAVIGATION_FILE = SITE_DIR / "src" / "data" / "navigation.json"
FOOTER_FILE = SITE_DIR / "src" / "data" / "footer.json"
CONSTS_FILE = SITE_DIR / "src" / "consts.ts"
THEME_FILE = SITE_DIR / "src" / "data" / "theme.json"
PUBLIC_UPLOADS_DIR = SITE_DIR / "public" / "uploads"
PUBLIC_FONTS_DIR = SITE_DIR / "public" / "fonts"
DEFAULT_HOME: dict[str, Any] = {
    "kicker": "个人博客 / 学习记录 / 项目日志",
    "title": "把折腾过的东西，慢慢写成能回看的记录。",
    "description": "这里先放学习笔记、建站过程、项目复盘和一些日常想法。内容还在搭建中，现在的文章和图片有不少是占位，后面会逐步替换成真实记录。",
    "primaryLabel": "看文章",
    "primaryHref": "/blog/",
    "secondaryLabel": "看友链",
    "secondaryHref": "/links/",
    "panelEyebrow": "当前状态",
    "panelTitle": "Cloudflare Pages 静态部署",
    "panelText": "Astro 生成页面，Markdown/MDX 写文章。没有数据库，没有后台服务，适合低成本长期维护。",
    "heroBackground": "",
    "heroOverlayStart": 0.72,
    "heroOverlayEnd": 0.42,
    "heroPanelOpacity": 0.82,
    "primaryButtonOpacity": 1.0,
    "secondaryButtonOpacity": 0.86,
    "showLatestPosts": True,
    "showTopics": True,
    "sections": [],
}
DEFAULT_NAVIGATION: list[dict[str, Any]] = [
    {"label": "首页", "href": "/", "enabled": True},
    {"label": "文章", "href": "/blog", "enabled": True},
    {"label": "归档", "href": "/archive", "enabled": True},
    {"label": "标签", "href": "/tags", "enabled": True},
    {"label": "搜索", "href": "/search", "enabled": True},
    {"label": "友链", "href": "/links", "enabled": True},
    {"label": "关于", "href": "/about", "enabled": True},
]
DEFAULT_FOOTER: dict[str, Any] = {
    "copyright": "© {year} ztt. All rights reserved.",
    "description": "ztt 的网站 使用 Astro 构建，托管在 Cloudflare Pages。",
    "rssLabel": "RSS",
    "rssHref": "/rss.xml",
    "showRss": True,
    "douyinHref": "",
    "bilibiliHref": "",
}
DEFAULT_THEME: dict[str, Any] = {
    "bodyFont": "default",
    "headingFont": "default",
    "navFont": "default",
    "homeTitleFont": "default",
    "homeTextFont": "default",
    "postTitleFont": "default",
    "postBodyFont": "default",
    "footerFont": "default",
    "customFonts": [],
}
BUILTIN_FONT_OPTIONS: list[dict[str, str]] = [
    {"id": "default", "label": "默认 Atkinson + 中文系统字体"},
    {"id": "serif", "label": "文艺宋体"},
    {"id": "wenkai", "label": "温和文楷"},
    {"id": "sans", "label": "现代黑体"},
    {"id": "system", "label": "系统界面字体"},
]


def node_modules_ready() -> bool:
    return (SITE_DIR / "node_modules").is_dir()


def run_command(cmd: list[str], cwd: Path = ROOT, timeout: int = 120) -> CommandResult:
    env = os.environ.copy()
    env["ASTRO_TELEMETRY_DISABLED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part for part in [exc.stdout, exc.stderr, "Command timed out."] if part)
        return CommandResult(124, output)
    except FileNotFoundError:
        return CommandResult(127, f"Command not found: {cmd[0]}")

    return CommandResult(result.returncode, "\n".join(part for part in [result.stdout, result.stderr] if part).strip())


def npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def check_requirements() -> CommandResult:
    messages: list[str] = []
    code = 0

    messages.append(f"项目目录：{ROOT}")
    messages.append(f"站点目录：{SITE_DIR}")

    for name in ["git", "node", npm_command()]:
        path = shutil.which(name)
        if path:
            messages.append(f"已找到 {name}：{path}")
        else:
            messages.append(f"未找到 {name}。请先安装 Git 和 Node.js，然后重新打开控制面板。")
            code = 1

    if node_modules_ready():
        messages.append("依赖状态：site/node_modules 已存在。")
    else:
        messages.append("依赖状态：site/node_modules 不存在。换电脑首次使用时，请点击“安装/更新依赖”。")

    result = run_command(["git", "remote", "-v"], timeout=20)
    if result.code == 0 and result.output.strip():
        messages.append("\nGit 远程仓库：")
        messages.append(result.output)
    else:
        messages.append("\nGit 远程仓库：未配置或读取失败。")

    return CommandResult(code, "\n".join(messages))


def install_dependencies() -> CommandResult:
    npm = shutil.which(npm_command())
    if not npm:
        return CommandResult(1, "没有找到 npm。请先安装 Node.js 22.12 或更新版本。")

    command = [npm_command(), "install"]
    if (SITE_DIR / "package-lock.json").exists():
        command = [npm_command(), "ci"]

    result = run_command(command, cwd=SITE_DIR, timeout=300)
    if result.code == 0:
        return CommandResult(0, "依赖安装完成。\n\n" + result.output)
    return CommandResult(result.code, result.output)


def slugify(title: str) -> str:
    text = title.strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff-]+", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or f"post-{int(time.time())}"


def yaml_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def set_draft_frontmatter(text: str, draft: bool) -> str:
    value = "true" if draft else "false"
    if text.startswith("---\r\n"):
        newline = "\r\n"
        frontmatter_start = 5
    elif text.startswith("---\n"):
        newline = "\n"
        frontmatter_start = 4
    else:
        return f"---\ndraft: {value}\n---\n\n{text}"

    closing = re.search(r"(?m)^---[ \t]*\r?$", text[frontmatter_start:])
    if not closing:
        return text
    closing_start = frontmatter_start + closing.start()
    frontmatter = text[frontmatter_start:closing_start]
    pattern = re.compile(
        r"^(draft[ \t]*:[ \t]*)(?:true|false)([ \t]*(?:#.*)?)(\r?)$",
        re.MULTILINE | re.IGNORECASE,
    )
    if pattern.search(frontmatter):
        updated = pattern.sub(
            lambda match: f"{match.group(1)}{value}{match.group(2)}{match.group(3)}",
            frontmatter,
            count=1,
        )
    else:
        updated = f"draft: {value}{newline}{frontmatter}"
    return text[:frontmatter_start] + updated + text[closing_start:]


def parse_checkbox(value: str) -> bool:
    return value == "on"


def parse_opacity(value: str, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return round(min(1.0, max(0.0, parsed)), 2)


def safe_filename(filename: str, fallback: str = "image") -> str:
    name = Path(filename).name.strip()
    stem = slugify(Path(name).stem or fallback)
    ext = Path(name).suffix.lower()
    return f"{stem}{ext}" if ext else stem


def font_format(ext: str) -> str:
    return {
        ".woff2": "woff2",
        ".woff": "woff",
        ".ttf": "truetype",
        ".otf": "opentype",
    }.get(ext.lower(), "woff2")


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}-{int(time.time())}{suffix}"


def save_public_image(upload: UploadedFile | None, folder: str, fallback: str = "image") -> str | None:
    if not upload or not upload.filename or not upload.data:
        return None
    filename = safe_filename(upload.filename, fallback)
    if Path(filename).suffix.lower() not in UPLOAD_IMAGE_EXTENSIONS:
        raise ValueError("图片只支持 jpg、jpeg、png、webp、avif、gif；为安全起见不接收 SVG 上传。")
    if len(upload.data) > MAX_UPLOAD_BYTES:
        raise ValueError("单个图片不能超过 12 MiB。")
    target_dir = PUBLIC_UPLOADS_DIR / folder
    target = unique_path(target_dir, filename)
    target.write_bytes(upload.data)
    return "/" + str(target.relative_to(SITE_DIR / "public")).replace("\\", "/")


def save_asset_image(upload: UploadedFile | None, folder: str, fallback: str = "image") -> tuple[Path, str] | None:
    if not upload or not upload.filename or not upload.data:
        return None
    filename = safe_filename(upload.filename, fallback)
    if Path(filename).suffix.lower() not in COVER_IMAGE_EXTENSIONS:
        raise ValueError("封面图只支持 jpg、jpeg、png、webp、avif。")
    if len(upload.data) > MAX_UPLOAD_BYTES:
        raise ValueError("单个封面图不能超过 12 MiB。")
    target_dir = ASSETS_DIR / folder
    target = unique_path(target_dir, filename)
    target.write_bytes(upload.data)
    return target, str(target.relative_to(ROOT))


def save_font_file(upload: UploadedFile | None, fallback: str = "font") -> tuple[str, str, str] | None:
    if not upload or not upload.filename or not upload.data:
        return None
    filename = safe_filename(upload.filename, fallback)
    ext = Path(filename).suffix.lower()
    if ext not in FONT_EXTENSIONS:
        raise ValueError("字体只支持 woff2、woff、ttf、otf。")
    if len(upload.data) > MAX_UPLOAD_BYTES:
        raise ValueError("单个字体文件不能超过 12 MiB。")
    target_dir = PUBLIC_FONTS_DIR / "custom"
    target = unique_path(target_dir, filename)
    target.write_bytes(upload.data)
    url = "/" + str(target.relative_to(SITE_DIR / "public")).replace("\\", "/")
    return url, font_format(ext), target.stem


def asset_path_for_post(asset: Path, post_path: Path) -> str:
    return Path(os.path.relpath(asset, post_path.parent)).as_posix()


def read_home() -> dict[str, Any]:
    data = DEFAULT_HOME.copy()
    if HOME_FILE.exists():
        loaded = json.loads(HOME_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    sections = data.get("sections", [])
    data["sections"] = sections if isinstance(sections, list) else []
    return data


def write_home(data: dict[str, Any]) -> None:
    HOME_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOME_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_navigation() -> list[dict[str, Any]]:
    if NAVIGATION_FILE.exists():
        loaded = json.loads(NAVIGATION_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            items = [item for item in loaded if isinstance(item, dict)]
            if items:
                return items
    return [item.copy() for item in DEFAULT_NAVIGATION]


def write_navigation(items: list[dict[str, Any]]) -> None:
    NAVIGATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    NAVIGATION_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_footer() -> dict[str, Any]:
    data = DEFAULT_FOOTER.copy()
    if FOOTER_FILE.exists():
        loaded = json.loads(FOOTER_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    return data


def write_footer(data: dict[str, Any]) -> None:
    FOOTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOOTER_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_theme() -> dict[str, Any]:
    data = DEFAULT_THEME.copy()
    if THEME_FILE.exists():
        loaded = json.loads(THEME_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    if not isinstance(data.get("customFonts"), list):
        data["customFonts"] = []
    return data


def write_theme(data: dict[str, Any]) -> None:
    THEME_FILE.parent.mkdir(parents=True, exist_ok=True)
    THEME_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def split_post_file(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")

    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    frontmatter = parse_frontmatter(path)
    body = text[end + len("\n---") :].lstrip("\r\n")
    return frontmatter, body


def post_path_from_rel(rel_file: str) -> Path | None:
    if not rel_file:
        return None
    path = (ROOT / rel_file).resolve()
    try:
        path.relative_to(POSTS_DIR.resolve())
    except ValueError:
        return None
    if not path.is_file() or path.suffix.lower() not in POST_EXTENSIONS:
        return None
    return path


def relative_to_root(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def safe_root_file(rel_file: str, *, must_exist: bool = True) -> Path | None:
    if not rel_file:
        return None
    raw = rel_file.replace("\\", "/").lstrip("/")
    path = (ROOT / raw).resolve()
    try:
        relative = path.relative_to(ROOT.resolve())
    except ValueError:
        return None
    if any(part in EDIT_EXCLUDED_PARTS or part.startswith(".tmp-") for part in relative.parts):
        return None
    if path.name in EDIT_EXCLUDED_NAMES:
        return None
    if path.suffix.lower() not in EDITABLE_EXTENSIONS:
        return None
    if must_exist and not path.is_file():
        return None
    return path


def list_editable_files() -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for current, dirs, names in os.walk(ROOT):
        dirs[:] = [
            name for name in dirs if name not in EDIT_EXCLUDED_PARTS and not name.startswith(".tmp-")
        ]
        current_path = Path(current)
        for name in names:
            path = current_path / name
            if name in EDIT_EXCLUDED_NAMES or path.suffix.lower() not in EDITABLE_EXTENSIONS:
                continue
            try:
                relative = path.relative_to(ROOT)
            except ValueError:
                continue
            rel = relative.as_posix()
            files.append({"file": rel, "name": rel, "kind": path.suffix.lower().lstrip(".") or "text"})
    return sorted(files, key=lambda item: item["file"])


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def page_file_for_href(href: str) -> str | None:
    clean_href = href.strip()
    if not clean_href or clean_href.startswith(("http://", "https://", "mailto:", "#")):
        return None
    path_part = clean_href.split("?", 1)[0].split("#", 1)[0].strip("/")
    candidates: list[Path]
    if not path_part:
        candidates = [SITE_DIR / "src" / "pages" / "index.astro"]
    else:
        candidates = [
            SITE_DIR / "src" / "pages" / f"{path_part}.astro",
            SITE_DIR / "src" / "pages" / path_part / "index.astro",
        ]
    for candidate in candidates:
        if candidate.is_file() and safe_root_file(relative_to_root(candidate)):
            return relative_to_root(candidate)
    return None


def route_for_page_file(path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to((SITE_DIR / "src" / "pages").resolve())
    except ValueError:
        return None
    if path.suffix.lower() != ".astro":
        return None
    if any(part.startswith("[") for part in relative.parts):
        return None

    parts = list(relative.parts)
    filename = parts.pop()
    stem = Path(filename).stem
    if stem != "index":
        parts.append(stem)
    route = "/" + "/".join(parts)
    return route.rstrip("/") + "/" if route != "/" else "/"


def split_yaml_flow_items(value: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    quote_char = ""
    index = 0
    while index < len(value):
        char = value[index]
        if quote_char:
            current.append(char)
            if char == quote_char:
                if index + 1 < len(value) and value[index + 1] == quote_char:
                    current.append(value[index + 1])
                    index += 1
                else:
                    quote_char = ""
            elif char == "\\" and quote_char == '"' and index + 1 < len(value):
                current.append(value[index + 1])
                index += 1
        elif char in {'"', "'"}:
            quote_char = char
            current.append(char)
        elif char == ",":
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    items.append("".join(current).strip())
    return [item for item in items if item]


def strip_yaml_inline_comment(value: str) -> str:
    quote_char = ""
    index = 0
    while index < len(value):
        char = value[index]
        if quote_char:
            if char == quote_char:
                if index + 1 < len(value) and value[index + 1] == quote_char:
                    index += 1
                else:
                    quote_char = ""
            elif char == "\\" and quote_char == '"':
                index += 1
        elif char in {'"', "'"}:
            quote_char = char
        elif char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        index += 1
    return value


def parse_yaml_scalar(raw_value: str) -> Any:
    value = strip_yaml_inline_comment(raw_value.strip())
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        return [parse_yaml_scalar(item) for item in split_yaml_flow_items(value[1:-1])]
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    return value


def parse_frontmatter_text(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    data: dict[str, Any] = {}
    for raw_line in text[3:end].splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        data[key.strip()] = parse_yaml_scalar(raw_value)
    return data


def parse_frontmatter(path: Path) -> dict[str, Any]:
    return parse_frontmatter_text(read_text_file(path))


MANAGED_POST_FIELDS = {"title", "description", "tags", "draft", "pubDate", "updatedDate", "heroImage"}
BLOCK_SCALAR_MARKERS = {"|", "|-", "|+", ">", ">-", ">+"}


def complex_managed_frontmatter_fields(text: str) -> list[str]:
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []

    lines = text[3:end].splitlines()
    complex_fields: list[str] = []
    for index, raw_line in enumerate(lines):
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", raw_line)
        if not match or match.group(1) not in MANAGED_POST_FIELDS:
            continue
        value = strip_yaml_inline_comment(match.group(2).strip())
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if value in BLOCK_SCALAR_MARKERS or (not value and next_line.startswith((" ", "\t"))):
            complex_fields.append(match.group(1))
    return complex_fields


def preserved_frontmatter_lines(text: str) -> list[str]:
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []

    preserved: list[str] = []
    keep_block = False
    for raw_line in text[3:end].splitlines():
        key_match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:", raw_line)
        if key_match:
            keep_block = key_match.group(1) not in MANAGED_POST_FIELDS
        if keep_block:
            preserved.append(raw_line)
    return preserved


def new_post_path_from_source(content: str, suffix: str) -> tuple[Path | None, str | None]:
    data = parse_frontmatter_text(content)
    title = str(data.get("title", "")).strip()
    if not title:
        return None, "新文章源码 frontmatter 里需要有 title。"
    pub_date = str(data.get("pubDate", "")).strip() or date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", pub_date):
        pub_date = date.today().isoformat()
    extension = ".mdx" if suffix == ".mdx" else ".md"
    path = POSTS_DIR / f"{pub_date}-{slugify(title)}{extension}"
    if path.exists():
        return None, f"文章已存在：{relative_to_root(path)}"
    return path, None


def template_path_from_rel(rel_file: str) -> Path | None:
    if not rel_file:
        return None
    raw = rel_file.replace("\\", "/").lstrip("/")
    path = (POST_TEMPLATES_DIR / raw).resolve()
    try:
        path.relative_to(POST_TEMPLATES_DIR.resolve())
    except ValueError:
        return None
    if not path.is_file() or path.suffix.lower() not in POST_EXTENSIONS:
        return None
    return path


def list_post_templates() -> list[dict[str, str]]:
    templates: list[dict[str, str]] = []
    if not POST_TEMPLATES_DIR.exists():
        return templates
    for path in sorted(POST_TEMPLATES_DIR.glob("*")):
        if path.suffix.lower() not in POST_EXTENSIONS:
            continue
        data = parse_frontmatter(path)
        templates.append(
            {
                "file": path.relative_to(POST_TEMPLATES_DIR).as_posix(),
                "name": path.name,
                "title": str(data.get("title", path.stem)),
                "kind": path.suffix.lower().lstrip("."),
            }
        )
    return templates


def source_from_template(template_rel: str, title: str, description: str, tags: list[str], draft: bool, pub_date: str) -> tuple[str, str]:
    path = template_path_from_rel(template_rel)
    if not path:
        return default_post_source(title, description, tags, draft, pub_date), ".md"

    text = read_text_file(path)
    suffix = path.suffix.lower() if path.suffix.lower() in POST_EXTENSIONS else ".md"
    tag_text = "[" + ", ".join(yaml_quote(tag) for tag in tags) + "]"
    replacements = {
        "title": yaml_quote(title),
        "description": yaml_quote(description),
        "tags": tag_text,
        "draft": "true" if draft else "false",
        "pubDate": yaml_quote(pub_date),
    }
    for key, value in replacements.items():
        if re.search(rf"(?m)^{key}:\s*.*$", text):
            text = re.sub(rf"(?m)^{key}:\s*.*$", f"{key}: {value}", text, count=1)
        elif text.startswith("---\n"):
            text = text.replace("---\n", f"---\n{key}: {value}\n", 1)
    return text, suffix


def save_post_as_template(form: dict[str, str]) -> CommandResult:
    path = post_path_from_rel(form.get("file", "").strip())
    if not path:
        return CommandResult(1, "文章路径无效，无法保存为模板。")
    data = parse_frontmatter(path)
    title = str(data.get("title", path.stem)).strip() or path.stem
    filename = f"{slugify(title)}{path.suffix.lower() if path.suffix.lower() in POST_EXTENSIONS else '.md'}"
    target = unique_path(POST_TEMPLATES_DIR, filename)
    text = read_text_file(path)
    text = set_draft_frontmatter(text, True)
    target.write_text(text, encoding="utf-8")
    return CommandResult(0, f"已保存为模板：{target.relative_to(ROOT)}")


def initialize_post_templates() -> None:
    POST_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    if any(POST_TEMPLATES_DIR.glob("*.md")) or any(POST_TEMPLATES_DIR.glob("*.mdx")):
        return
    for post in list_posts()[:6]:
        path = post_path_from_rel(post["file"])
        if not path:
            continue
        target = POST_TEMPLATES_DIR / f"{slugify(str(post['title']))}{path.suffix.lower()}"
        if target.exists():
            continue
        text = read_text_file(path)
        text = set_draft_frontmatter(text, True)
        target.write_text(text, encoding="utf-8")


def list_posts() -> list[dict[str, Any]]:
    posts = []
    for path in sorted(POSTS_DIR.glob("**/*")):
        if path.suffix.lower() not in {".md", ".mdx"}:
            continue
        data = parse_frontmatter(path)
        posts.append(
            {
                "file": str(path.relative_to(ROOT)),
                "name": path.name,
                "title": data.get("title", path.stem),
                "date": data.get("pubDate", ""),
                "draft": bool(data.get("draft", False)),
                "tags": data.get("tags", []),
            }
        )
    return sorted(posts, key=lambda item: str(item["date"]), reverse=True)


def get_post_for_edit(rel_file: str) -> dict[str, Any] | None:
    path = post_path_from_rel(rel_file)
    if not path:
        return None

    data, body = split_post_file(path)
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        tags = []

    return {
        "file": str(path.relative_to(ROOT)),
        "name": path.name,
        "title": data.get("title", path.stem),
        "description": data.get("description", ""),
        "tags": ", ".join(str(tag) for tag in tags),
        "draft": bool(data.get("draft", False)),
        "pubDate": data.get("pubDate", ""),
        "updatedDate": data.get("updatedDate", ""),
        "heroImage": data.get("heroImage", ""),
        "body": body,
    }


def read_friends() -> list[dict[str, str]]:
    if not FRIENDS_FILE.exists():
        return []
    data = json.loads(FRIENDS_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def write_friends(friends: list[dict[str, str]]) -> None:
    FRIENDS_FILE.write_text(
        json.dumps(friends, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_multipart_multi(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, list[UploadedFile]]]:
    marker = "boundary="
    if marker not in content_type:
        return {}, {}
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    delimiter = ("--" + boundary).encode("utf-8")
    form: dict[str, str] = {}
    files: dict[str, list[UploadedFile]] = {}

    for part in body.split(delimiter):
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if not part or part == b"--" or b"\r\n\r\n" not in part:
            continue
        raw_headers, payload = part.split(b"\r\n\r\n", 1)
        headers = raw_headers.decode("utf-8", errors="replace").split("\r\n")
        disposition = ""
        part_type = ""
        for header in headers:
            key, _, value = header.partition(":")
            if key.lower() == "content-disposition":
                disposition = value.strip()
            elif key.lower() == "content-type":
                part_type = value.strip()
        name_match = re.search(r'name="([^"]+)"', disposition)
        if not name_match:
            continue
        field_name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if filename_match:
            filename = filename_match.group(1)
            if filename and payload:
                files.setdefault(field_name, []).append(UploadedFile(filename, part_type, payload))
        else:
            form[field_name] = payload.decode("utf-8", errors="replace")
    return form, files


def parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, UploadedFile]]:
    form, multi_files = parse_multipart_multi(body, content_type)
    return form, {key: values[-1] for key, values in multi_files.items() if values}


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def get_preview_url(port: int | None = None) -> str:
    selected_port = active_preview_port if port is None else port
    return f"http://{PREVIEW_HOST}:{selected_port}/"


def is_preview_ready(host: str, port: int, timeout: float = 0.8) -> bool:
    request = urllib.request.Request(
        f"http://{host}:{port}/",
        headers={"Accept": "text/html", "User-Agent": "ztt-blog-panel"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (OSError, TimeoutError, urllib.error.URLError):
        return False


def is_panel_ready(port: int, timeout: float = 0.8) -> bool:
    request = urllib.request.Request(
        f"http://{PANEL_HOST}:{port}/",
        headers={"Accept": "text/html", "User-Agent": "ztt-blog-panel"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read(128 * 1024)
            return response.status == 200 and "博客控制面板".encode("utf-8") in content
    except (OSError, TimeoutError, urllib.error.URLError):
        return False


def get_preview_state() -> tuple[str, bool]:
    process = preview_process
    port = active_preview_port
    url = get_preview_url(port)
    ready = bool(
        process
        and process.poll() is None
        and is_preview_ready(PREVIEW_HOST, port)
    )
    return url, ready


def is_owned_preview_ready() -> bool:
    return get_preview_state()[1]


def find_available_preview_port(
    host: str = PREVIEW_HOST,
    start_port: int = PREVIEW_PORT,
    attempts: int = PREVIEW_PORT_ATTEMPTS,
) -> int | None:
    for port in range(start_port, start_port + attempts):
        if not is_port_open(host, port):
            return port
    return None


def wait_for_port_closed(host: str, port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_port_open(host, port):
            return True
        time.sleep(0.1)
    return not is_port_open(host, port)


def collect_preview_output(process: subprocess.Popen[str]) -> None:
    if process.stdout is None:
        return
    try:
        for line in process.stdout:
            cleaned = line.rstrip()
            if cleaned:
                with preview_output_lock:
                    preview_output.append(cleaned)
    except (OSError, ValueError):
        pass


def launch_preview_process(npm: str, port: int) -> subprocess.Popen[str]:
    global preview_output_thread
    env = os.environ.copy()
    env["ASTRO_TELEMETRY_DISABLED"] = "1"
    if preview_output_thread and preview_output_thread.is_alive():
        preview_output_thread.join(timeout=1)
    with preview_output_lock:
        preview_output.clear()
    popen_options: dict[str, Any] = {
        "cwd": str(SITE_DIR),
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
        "env": env,
    }
    if os.name == "nt":
        popen_options["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        popen_options["start_new_session"] = True

    process = subprocess.Popen(
        [
            npm,
            "run",
            "dev",
            "--",
            "--host",
            PREVIEW_HOST,
            "--port",
            str(port),
        ],
        **popen_options,
    )
    preview_output_thread = threading.Thread(
        target=collect_preview_output,
        args=(process,),
        name="blog-preview-output",
        daemon=True,
    )
    preview_output_thread.start()
    return process


def terminate_preview_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result and result.returncode == 0:
            try:
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=5)
            return
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
            pass

    try:
        process.terminate()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass


def preview_output_tail() -> str:
    if preview_output_thread:
        preview_output_thread.join(timeout=0.2)
    with preview_output_lock:
        return "\n".join(preview_output)[-4000:]


def preview_port_from_output() -> int | None:
    with preview_output_lock:
        lines = list(preview_output)
    for line in reversed(lines):
        if "Local" not in line:
            continue
        match = re.search(r"https?://(?:127\.0\.0\.1|localhost):(\d{1,5})(?:/|\s|$)", line)
        if match:
            port = int(match.group(1))
            if 1 <= port <= 65535:
                return port
    return None


def get_git_status() -> str:
    result = run_command(["git", "status", "--short"], timeout=20)
    if result.code != 0:
        return result.output or "Git status failed."
    return result.output or "工作区干净。"


def get_site_url() -> str:
    if CONSTS_FILE.exists():
        text = read_text_file(CONSTS_FILE)
        match = re.search(r"export\s+const\s+SITE_URL\s*=\s*['\"]([^'\"]+)['\"]", text)
        if match:
            return match.group(1).rstrip("/")
    return "https://www.200302.xyz"


def default_post_source(title: str, description: str, tags: list[str], draft: bool, pub_date: str) -> str:
    tag_text = "[" + ", ".join(yaml_quote(tag) for tag in tags) + "]"
    return f"""---
title: {yaml_quote(title)}
description: {yaml_quote(description)}
tags: {tag_text}
draft: {'true' if draft else 'false'}
pubDate: {yaml_quote(pub_date)}
heroImage: '../../assets/blog-placeholder-1.jpg'
---

这里先写正文。

## 提纲

- 想说明的问题
- 过程中的记录
- 最后的总结
"""


def validate_post_metadata(title: str, description: str, tags: list[str]) -> str | None:
    if not title:
        return "请填写文章标题。"
    if len(title) > 80:
        return "文章标题最多 80 个字符。"
    if not description:
        return "请填写文章摘要。"
    if len(description) > 180:
        return "文章摘要最多 180 个字符。"
    if len(tags) > 8:
        return "一篇文章最多使用 8 个标签。"
    if any(not tag or len(tag) > 30 for tag in tags):
        return "每个标签必须为 1-30 个字符。"
    return None


def create_post(form: dict[str, str]) -> CommandResult:
    title = form.get("title", "").strip()
    description = form.get("description", "").strip() or "这是一篇新的博客文章。"
    tags = [tag.strip() for tag in re.split(r"[,，]", form.get("tags", "")) if tag.strip()]
    validation_error = validate_post_metadata(title, description, tags)
    if validation_error:
        return CommandResult(1, validation_error)
    draft = form.get("draft", "") == "on"
    pub_date = form.get("pubDate", "").strip() or date.today().isoformat()
    suffix = ".mdx" if form.get("format") == "mdx" else ".md"
    filename = f"{pub_date}-{slugify(title)}{suffix}"
    path = POSTS_DIR / filename

    if path.exists():
        return CommandResult(1, f"文章已存在：{path.relative_to(ROOT)}")

    path.write_text(default_post_source(title, description, tags, draft, pub_date), encoding="utf-8")
    return CommandResult(0, f"已创建文章：{path.relative_to(ROOT)}")


def publish_post(form: dict[str, str]) -> CommandResult:
    rel_file = form.get("file", "").strip()
    if not rel_file:
        return CommandResult(1, "请选择要发布的文章。")
    path = (ROOT / rel_file).resolve()
    if not path.is_file() or POSTS_DIR not in path.parents:
        return CommandResult(1, "文章路径无效。")

    text = set_draft_frontmatter(path.read_text(encoding="utf-8"), False)
    path.write_text(text, encoding="utf-8")
    return CommandResult(0, f"已标记为发布：{path.relative_to(ROOT)}")


def set_post_visibility(form: dict[str, str]) -> CommandResult:
    path = post_path_from_rel(form.get("file", "").strip())
    if not path:
        return CommandResult(1, "文章路径无效。")
    visible = form.get("visible", "true") == "true"
    text = read_text_file(path)
    text = set_draft_frontmatter(text, not visible)
    path.write_text(text, encoding="utf-8")
    return CommandResult(0, f"已{'显示' if visible else '隐藏'}文章：{relative_to_root(path)}")


def save_post(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    path = post_path_from_rel(form.get("file", "").strip())
    if not path:
        return CommandResult(1, "文章路径无效。")

    original_source = read_text_file(path)
    complex_fields = complex_managed_frontmatter_fields(original_source)
    if complex_fields:
        fields = "、".join(complex_fields)
        return CommandResult(1, f"这篇文章的 {fields} 使用了高级 YAML 格式。请改用源码编辑器保存，避免格式被改坏。")
    existing_tags = parse_frontmatter_text(original_source).get("tags", [])
    if isinstance(existing_tags, list) and any("," in str(tag) or "，" in str(tag) for tag in existing_tags):
        return CommandResult(1, "这篇文章有包含逗号的标签。请改用源码编辑器保存，避免标签被拆开。")

    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    pub_date = form.get("pubDate", "").strip() or date.today().isoformat()
    updated_date = form.get("updatedDate", "").strip()
    hero_image = form.get("heroImage", "").strip()
    body = form.get("body", "").replace("\r\n", "\n").strip()
    tags = [tag.strip() for tag in re.split(r"[,，]", form.get("tags", "")) if tag.strip()]
    validation_error = validate_post_metadata(title, description, tags)
    if validation_error:
        return CommandResult(1, validation_error)
    draft = parse_checkbox(form.get("draft", ""))

    try:
        cover_upload = save_asset_image((files or {}).get("heroImageFile"), "covers", slugify(title))
    except ValueError as exc:
        return CommandResult(1, str(exc))
    if cover_upload:
        hero_image = asset_path_for_post(cover_upload[0], path)

    preserved_lines = preserved_frontmatter_lines(original_source)
    lines = [
        "---",
        f"title: {yaml_quote(title)}",
        f"description: {yaml_quote(description)}",
        "tags: [" + ", ".join(yaml_quote(tag) for tag in tags) + "]",
        f"draft: {'true' if draft else 'false'}",
        f"pubDate: {yaml_quote(pub_date)}",
    ]
    if updated_date:
        lines.append(f"updatedDate: {yaml_quote(updated_date)}")
    if hero_image:
        lines.append(f"heroImage: {yaml_quote(hero_image)}")
    lines.extend(preserved_lines)
    lines.extend(["---", "", body, ""])

    path.write_text("\n".join(lines), encoding="utf-8")
    return CommandResult(0, f"已保存文章：{path.relative_to(ROOT)}")


def insert_post_image(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    path = post_path_from_rel(form.get("file", "").strip())
    if not path:
        return CommandResult(1, "请选择要插入图片的文章。")

    upload = (files or {}).get("image")
    if not upload or not upload.filename:
        return CommandResult(1, "请选择一张图片。")

    alt = form.get("alt", "").strip() or Path(upload.filename).stem
    try:
        image_path = save_public_image(upload, "posts", slugify(alt))
    except ValueError as exc:
        return CommandResult(1, str(exc))
    if not image_path:
        return CommandResult(1, "图片保存失败。")

    markdown = f"\n\n![{alt}]({image_path})\n"
    with path.open("a", encoding="utf-8") as file:
        file.write(markdown)
    return CommandResult(0, f"已把图片插入到文章末尾：{image_path}\n\nMarkdown：![{alt}]({image_path})")


def save_source_file(form: dict[str, str]) -> CommandResult:
    rel_file = form.get("file", "").strip()
    content = form.get("content", "").replace("\r\n", "\n")
    if rel_file == "__new_post__":
        suffix = form.get("suffix", ".md")
        path, error = new_post_path_from_source(content, suffix)
        if not path:
            return CommandResult(1, error or "无法创建新文章。")
    else:
        path = safe_root_file(rel_file)
        if not path:
            return CommandResult(1, "文件路径无效，或这个文件类型不允许在面板里编辑。")
    path.write_text(content, encoding="utf-8")
    return CommandResult(0, f"已保存：{relative_to_root(path)}")


def upload_editor_images(multi_files: dict[str, list[UploadedFile]]) -> CommandResult:
    uploads = multi_files.get("images", [])
    if not uploads:
        return CommandResult(1, "请选择至少一张图片。")
    if len(uploads) > MAX_UPLOAD_FILES:
        return CommandResult(1, f"一次最多上传 {MAX_UPLOAD_FILES} 张图片。")

    for upload in uploads:
        filename = safe_filename(upload.filename, "image")
        if Path(filename).suffix.lower() not in UPLOAD_IMAGE_EXTENSIONS:
            return CommandResult(1, "图片只支持 jpg、jpeg、png、webp、avif、gif；为安全起见不接收 SVG 上传。")
        if len(upload.data) > MAX_UPLOAD_BYTES:
            return CommandResult(1, "单个图片不能超过 12 MiB。")

    snippets: list[str] = []
    for upload in uploads:
        alt = Path(upload.filename).stem or "image"
        try:
            image_path = save_public_image(upload, "posts", slugify(alt))
        except ValueError as exc:
            return CommandResult(1, str(exc))
        if image_path:
            snippets.append(f"![{alt}]({image_path})")

    if not snippets:
        return CommandResult(1, "图片保存失败。")
    return CommandResult(0, "\n\n".join(snippets))


def update_home_settings(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    home = read_home()
    for key in [
        "kicker",
        "title",
        "description",
        "primaryLabel",
        "primaryHref",
        "secondaryLabel",
        "secondaryHref",
        "panelEyebrow",
        "panelTitle",
        "panelText",
    ]:
        home[key] = form.get(key, "").strip()
    home["showLatestPosts"] = parse_checkbox(form.get("showLatestPosts", ""))
    home["showTopics"] = parse_checkbox(form.get("showTopics", ""))
    home["heroOverlayStart"] = parse_opacity(form.get("heroOverlayStart", ""), 0.72)
    home["heroOverlayEnd"] = parse_opacity(form.get("heroOverlayEnd", ""), 0.42)
    home["heroPanelOpacity"] = parse_opacity(form.get("heroPanelOpacity", ""), 0.82)
    home["primaryButtonOpacity"] = parse_opacity(form.get("primaryButtonOpacity", ""), 1.0)
    home["secondaryButtonOpacity"] = parse_opacity(form.get("secondaryButtonOpacity", ""), 0.86)

    try:
        background = save_public_image((files or {}).get("heroBackgroundFile"), "home", "home-background")
    except ValueError as exc:
        return CommandResult(1, str(exc))
    if background:
        home["heroBackground"] = background
    elif parse_checkbox(form.get("clearHeroBackground", "")):
        home["heroBackground"] = ""
    else:
        home["heroBackground"] = form.get("heroBackground", "").strip()

    sections = home.get("sections", [])
    current = sections[0] if sections and isinstance(sections[0], dict) else {}
    if parse_checkbox(form.get("deleteSection", "")):
        home["sections"] = []
    else:
        section = {
            "id": current.get("id", "custom-section"),
            "enabled": parse_checkbox(form.get("sectionEnabled", "")),
            "eyebrow": form.get("sectionEyebrow", "").strip(),
            "title": form.get("sectionTitle", "").strip(),
            "body": form.get("sectionBody", "").strip(),
            "linkLabel": form.get("sectionLinkLabel", "").strip(),
            "linkHref": form.get("sectionLinkHref", "").strip(),
        }
        home["sections"] = [section] if section["title"] or section["body"] else []
    write_home(home)
    return CommandResult(0, "首页设置已保存。启动预览或构建后就能看到效果。")


def update_navigation(form: dict[str, str]) -> CommandResult:
    items = read_navigation()
    updated: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        if parse_checkbox(form.get(f"delete_{index}", "")):
            continue
        label = form.get(f"label_{index}", "").strip()
        href = form.get(f"href_{index}", "").strip()
        if not label or not href:
            continue
        try:
            order = int(form.get(f"order_{index}", str(index + 1)))
        except ValueError:
            order = index + 1
        updated.append(
            {
                "label": label,
                "href": href,
                "enabled": parse_checkbox(form.get(f"enabled_{index}", "")),
                "_order": order,
            }
        )

    new_label = form.get("new_label", "").strip()
    new_href = form.get("new_href", "").strip()
    if new_label and new_href:
        try:
            new_order = int(form.get("new_order", str(len(updated) + 1)))
        except ValueError:
            new_order = len(updated) + 1
        updated.append(
            {
                "label": new_label,
                "href": new_href,
                "enabled": parse_checkbox(form.get("new_enabled", "on")),
                "_order": new_order,
            }
        )

    updated.sort(key=lambda item: item.get("_order", 999))
    for item in updated:
        item.pop("_order", None)
    if not updated:
        return CommandResult(1, "导航栏至少保留一个栏目。")
    write_navigation(updated)
    return CommandResult(0, "导航栏目已保存。刷新预览即可看到变化。")


def update_footer(form: dict[str, str]) -> CommandResult:
    footer = {
        "copyright": form.get("copyright", "").strip() or DEFAULT_FOOTER["copyright"],
        "description": form.get("description", "").strip(),
        "rssLabel": form.get("rssLabel", "").strip() or "RSS",
        "rssHref": form.get("rssHref", "").strip() or "/rss.xml",
        "showRss": parse_checkbox(form.get("showRss", "")),
        "douyinHref": form.get("douyinHref", "").strip(),
        "bilibiliHref": form.get("bilibiliHref", "").strip(),
    }
    write_footer(footer)
    return CommandResult(0, "底部信息已保存。刷新预览即可看到变化。")


def update_theme(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    theme = read_theme()
    custom_fonts = [font for font in theme.get("customFonts", []) if isinstance(font, dict)]

    family = form.get("fontFamily", "").strip()
    weight = form.get("fontWeight", "").strip() or "400"
    upload = (files or {}).get("fontFile")
    if upload and upload.filename:
        if not family:
            family = Path(upload.filename).stem
        if not re.fullmatch(r"[\w -]{1,80}", family, flags=re.UNICODE):
            return CommandResult(1, "字体名称只能包含文字、数字、空格、下划线和连字符。")
        if not re.fullmatch(r"(?:normal|bold|[1-9]00)", weight):
            return CommandResult(1, "字体粗细无效。")
        try:
            url, fmt, stem = save_font_file(upload, slugify(family or "custom-font"))
        except ValueError as exc:
            return CommandResult(1, str(exc))
        font_id = f"custom-{slugify(family or stem)}-{int(time.time())}"
        custom_fonts.append(
            {
                "id": font_id,
                "label": family,
                "family": family,
                "url": url,
                "format": fmt,
                "weight": weight,
            }
        )
        if parse_checkbox(form.get("applyUploadedToBody", "")):
            theme["bodyFont"] = font_id
        if parse_checkbox(form.get("applyUploadedToHeading", "")):
            theme["headingFont"] = font_id

    available_ids = {item["id"] for item in BUILTIN_FONT_OPTIONS}
    available_ids.update(str(font.get("id")) for font in custom_fonts)
    for key in [
        "bodyFont",
        "headingFont",
        "navFont",
        "homeTitleFont",
        "homeTextFont",
        "postTitleFont",
        "postBodyFont",
        "footerFont",
    ]:
        value = form.get(key, "").strip()
        if value in available_ids:
            theme[key] = value

    theme["customFonts"] = custom_fonts
    write_theme(theme)
    return CommandResult(0, "字体设置已保存。构建并发布后，访客会加载网站托管的字体文件。")


def add_friend(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    name = form.get("name", "").strip()
    url = form.get("url", "").strip()
    description = form.get("description", "").strip()
    avatar = form.get("avatar", "").strip() or "/favicon.svg"
    if not name or not url:
        return CommandResult(1, "友链名称和链接必填。")

    try:
        uploaded_avatar = save_public_image((files or {}).get("avatarFile"), "avatars", slugify(name))
    except ValueError as exc:
        return CommandResult(1, str(exc))
    if uploaded_avatar:
        avatar = uploaded_avatar

    friends = read_friends()
    friends.append(
        {
            "name": name,
            "url": url,
            "description": description or "新的朋友站点。",
            "avatar": avatar,
        }
    )
    write_friends(friends)
    return CommandResult(0, f"已添加友链：{name}")


def delete_friend(form: dict[str, str]) -> CommandResult:
    url = form.get("url", "").strip()
    friends = read_friends()
    kept = [friend for friend in friends if friend.get("url") != url]
    if len(kept) == len(friends):
        return CommandResult(1, "没有找到这条友链。")
    write_friends(kept)
    return CommandResult(0, "已删除友链。")


def start_preview() -> CommandResult:
    global active_preview_port, preview_process
    with preview_lock:
        npm = shutil.which(npm_command())
        if not npm:
            return CommandResult(1, "没有找到 npm。请先安装 Node.js 22.12 或更新版本。")
        if not node_modules_ready():
            return CommandResult(1, "还没有安装依赖。请先点击“安装/更新依赖”。")
        if preview_process and preview_process.poll() is None:
            if is_preview_ready(PREVIEW_HOST, active_preview_port):
                return CommandResult(0, f"预览服务已在 {get_preview_url()} 运行。")
            terminate_preview_process(preview_process)
        preview_process = None

        selected_port = find_available_preview_port()
        if selected_port is None:
            end_port = PREVIEW_PORT + PREVIEW_PORT_ATTEMPTS - 1
            return CommandResult(
                1,
                f"端口 {PREVIEW_PORT}-{end_port} 都被占用，无法启动预览。请关闭其他本地开发服务后重试。",
            )
        active_preview_port = selected_port

        try:
            preview_process = launch_preview_process(npm, selected_port)
        except OSError as exc:
            preview_process = None
            active_preview_port = PREVIEW_PORT
            return CommandResult(1, f"预览进程启动失败：{exc}")

        deadline = time.monotonic() + PREVIEW_START_TIMEOUT_SECONDS
        exit_code: int | None = None
        while time.monotonic() < deadline:
            exit_code = preview_process.poll()
            if exit_code is not None:
                break
            detected_port = preview_port_from_output()
            if detected_port is not None:
                active_preview_port = detected_port
            if detected_port is not None and is_preview_ready(PREVIEW_HOST, detected_port):
                fallback_note = (
                    ""
                    if detected_port == PREVIEW_PORT
                    else f"\n\n端口 {PREVIEW_PORT} 已被占用，已自动改用 {detected_port}。"
                )
                return CommandResult(0, f"已启动预览：{get_preview_url()}{fallback_note}")
            time.sleep(0.2)

        if exit_code is None and preview_process:
            terminate_preview_process(preview_process)
        details = preview_output_tail()
        preview_process = None
        active_preview_port = PREVIEW_PORT
        if exit_code is not None:
            summary = f"预览进程提前退出（退出码 {exit_code}）。"
        else:
            summary = f"等待 {PREVIEW_START_TIMEOUT_SECONDS:g} 秒后预览仍未就绪。"
        if details:
            summary += "\n\n最近日志：\n" + details
        return CommandResult(1, summary)


def stop_preview() -> CommandResult:
    global active_preview_port, preview_process
    with preview_lock:
        if preview_process:
            port = active_preview_port
            terminate_preview_process(preview_process)
            preview_process = None
            active_preview_port = PREVIEW_PORT
            if not wait_for_port_closed(PREVIEW_HOST, port):
                return CommandResult(
                    1,
                    f"已尝试停止预览，但端口 {port} 仍被占用。请关闭控制面板后重新打开。",
                )
            return CommandResult(0, f"已停止端口 {port} 的预览服务。")
    return CommandResult(0, "当前没有由面板启动的预览服务。")


def build_site() -> CommandResult:
    if not shutil.which(npm_command()):
        return CommandResult(1, "没有找到 npm。请先安装 Node.js 22.12 或更新版本。")
    if not node_modules_ready():
        return CommandResult(1, "还没有安装依赖。请先点击“安装/更新依赖”。")
    return run_command([npm_command(), "run", "build"], cwd=SITE_DIR, timeout=180)


def update_blog(form: dict[str, str]) -> CommandResult:
    message = form.get("message", "").strip() or "update blog"
    build = build_site()
    if build.code != 0:
        return CommandResult(build.code, "构建失败，已取消提交。\n\n" + build.output)
    result = run_command(
        [sys.executable, str(ROOT / "scripts" / "update_blog.py"), "-m", message, "--skip-build"],
        timeout=180,
    )
    return CommandResult(result.code, "构建已通过。\n\n" + result.output)


def html_escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def base_panel_css() -> str:
    return """
    :root {
      --accent:#ef4f9a;
      --accent-strong:#be185d;
      --accent-soft:#ffe4f1;
      --accent-2:#0f766e;
      --accent-2-soft:#d9f8ee;
      --ink:#172033;
      --muted:#667085;
      --line:#eadde7;
      --bg:#fff7fb;
      --surface:#fff;
      --surface-soft:#fffafd;
      --surface-tint:#fff3dc;
      --danger:#dc2626;
      --danger-soft:#fee2e2;
      --shadow:0 22px 70px rgba(146, 64, 110, .14);
      --shadow-soft:0 10px 32px rgba(146, 64, 110, .08);
      --radius:22px;
      --radius-sm:14px;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior:smooth; }
    body {
      min-height:100vh;
      margin:0;
      background:
        radial-gradient(circle at 8% 8%, rgba(255, 214, 239, .95), transparent 30rem),
        radial-gradient(circle at 92% 0%, rgba(196, 239, 255, .85), transparent 34rem),
        linear-gradient(135deg, #fffaf3 0%, #fff7fb 48%, #f3fbff 100%);
      color:var(--ink);
      font-family:"Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
      line-height:1.6;
    }
    body::before {
      position:fixed;
      inset:0;
      z-index:-1;
      pointer-events:none;
      content:"";
      background-image:
        linear-gradient(rgba(190, 24, 93, .045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(15, 118, 110, .045) 1px, transparent 1px);
      background-size:34px 34px;
      mask-image:linear-gradient(to bottom, rgba(0,0,0,.8), transparent 72%);
    }
    header {
      position:sticky;
      top:0;
      z-index:10;
      border-bottom:1px solid rgba(234, 221, 231, .8);
      background:rgba(255, 250, 253, .82);
      backdrop-filter:blur(20px);
      box-shadow:0 10px 30px rgba(146, 64, 110, .06);
    }
    .wrap { width:min(1240px, calc(100% - 32px)); margin:0 auto; }
    header .wrap { display:flex; justify-content:space-between; align-items:center; gap:18px; padding:18px 0; }
    main.wrap { padding:28px 0 56px; }
    h1,h2,h3 { margin:0 0 10px; line-height:1.18; letter-spacing:-.02em; }
    h1 { font-size:clamp(2rem, 4vw, 3.7rem); }
    h2 { font-size:clamp(1.25rem, 2vw, 1.7rem); }
    h3 { font-size:1.05rem; }
    p { margin:0 0 12px; }
    a { color:var(--accent-strong); }
    a:hover { color:#9d174d; }
    form { margin:0; }
    .muted { color:var(--muted); }
    .eyebrow {
      margin:0 0 8px;
      color:var(--accent-strong);
      font-size:.78rem;
      font-weight:900;
      letter-spacing:.16em;
      text-transform:uppercase;
    }
    .status { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:14px; margin:0 0 20px; }
    .metric {
      position:relative;
      overflow:hidden;
      min-height:118px;
      border:1px solid rgba(234, 221, 231, .9);
      border-radius:var(--radius);
      background:linear-gradient(145deg, rgba(255,255,255,.94), rgba(255,250,253,.82));
      padding:18px;
      box-shadow:var(--shadow-soft);
    }
    .metric::after {
      position:absolute;
      right:-26px;
      bottom:-30px;
      width:92px;
      height:92px;
      border-radius:999px;
      background:var(--accent-soft);
      content:"";
    }
    .metric.is-ok::after { background:var(--accent-2-soft); }
    .metric.is-warn::after { background:var(--surface-tint); }
    .metric strong { position:relative; z-index:1; display:block; font-size:clamp(1.65rem, 3vw, 2.35rem); line-height:1; letter-spacing:-.04em; }
    .metric span { position:relative; z-index:1; display:block; margin-top:10px; color:var(--muted); font-size:.9rem; font-weight:700; }
    .metric small { position:relative; z-index:1; display:block; margin-top:6px; color:#8a7180; font-size:.78rem; }
    .panel {
      border:1px solid rgba(234, 221, 231, .92);
      background:rgba(255,255,255,.88);
      border-radius:var(--radius);
      padding:20px;
      box-shadow:var(--shadow-soft);
    }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; align-items:start; }
    .section-title {
      grid-column:1 / -1;
      padding:26px 4px 6px;
    }
    .section-title h2 { margin:0 0 6px; }
    .section-title p { margin:0; color:var(--muted); }
    label { display:block; color:#6f5968; font-size:.9rem; font-weight:800; margin:12px 0 6px; }
    input, select, textarea {
      width:100%;
      min-height:44px;
      border:1px solid rgba(226, 200, 216, .95);
      border-radius:14px;
      background:rgba(255,255,255,.96);
      color:var(--ink);
      font:inherit;
      padding:10px 13px;
      outline:none;
      transition:border-color .16s ease, box-shadow .16s ease, background .16s ease;
    }
    input:focus, select:focus, textarea:focus {
      border-color:rgba(239, 79, 154, .78);
      box-shadow:0 0 0 4px rgba(239, 79, 154, .14);
      background:#fff;
    }
    input[type="number"] { min-width:72px; }
    input[type="range"] { min-height:34px; padding:0; accent-color:var(--accent); }
    input[type="file"] { padding:9px 12px; }
    input[type="checkbox"] { width:1.05rem; min-height:auto; accent-color:var(--accent); }
    textarea { min-height:96px; resize:vertical; }
    .body-editor { min-height:420px; font-family:Consolas, "Cascadia Mono", "Microsoft YaHei", monospace; line-height:1.58; }
    .hint { display:block; margin-top:6px; color:#81717d; font-size:.84rem; }
    .compact { display:flex; align-items:center; gap:8px; margin:8px 0; color:var(--ink); white-space:nowrap; }
    .compact input { width:auto; }
    .field-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px 16px; }
    .range-line { display:grid; grid-template-columns:minmax(0,1fr) 5rem; gap:10px; align-items:center; }
    button, .button {
      display:inline-flex;
      align-items:center;
      justify-content:center;
      min-height:44px;
      border:0;
      border-radius:999px;
      background:linear-gradient(135deg, var(--accent), var(--accent-strong));
      color:#fff;
      padding:9px 18px;
      font-weight:900;
      text-decoration:none;
      cursor:pointer;
      box-shadow:0 12px 28px rgba(190, 24, 93, .18);
      transition:transform .16s ease, box-shadow .16s ease, background .16s ease;
    }
    button:hover, .button:hover { transform:translateY(-1px); box-shadow:0 16px 34px rgba(190, 24, 93, .23); color:#fff; }
    button:focus-visible, .button:focus-visible { outline:3px solid rgba(239, 79, 154, .35); outline-offset:3px; }
    button.secondary, .button.secondary { background:#172033; color:#fff; box-shadow:0 12px 28px rgba(23, 32, 51, .14); }
    button.ghost, .button.ghost {
      min-height:38px;
      border:1px solid rgba(239, 79, 154, .18);
      background:rgba(255, 228, 241, .78);
      color:#9d174d;
      box-shadow:none;
    }
    button.ghost:hover, .button.ghost:hover { background:#ffd7eb; color:#831843; box-shadow:0 10px 24px rgba(190, 24, 93, .12); }
    button.danger, .button.danger { background:var(--danger-soft); color:var(--danger); }
    button.danger:hover, .button.danger:hover { background:#fecaca; color:#991b1b; box-shadow:0 10px 24px rgba(220, 38, 38, .13); }
    button:disabled, .button[aria-disabled="true"] { cursor:not-allowed; opacity:.48; transform:none; box-shadow:none; }
    .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }
    pre {
      white-space:pre-wrap;
      overflow:auto;
      max-height:360px;
      border-radius:16px;
      background:#161b2f;
      color:#edf2ff;
      padding:14px;
      box-shadow:inset 0 0 0 1px rgba(255,255,255,.06);
    }
    .result.ok { border-color:#86efac; background:linear-gradient(135deg,#f0fdf4,#fff); }
    .result.bad { border-color:#fca5a5; background:linear-gradient(135deg,#fff1f2,#fff); }
    table { width:100%; min-width:760px; border-collapse:separate; border-spacing:0; font-size:.91rem; }
    th,td { border-bottom:1px solid rgba(234, 221, 231, .86); text-align:left; padding:12px; vertical-align:top; }
    th { color:#7a6071; font-size:.78rem; font-weight:900; letter-spacing:.08em; text-transform:uppercase; }
    tr:last-child td { border-bottom:0; }
    tbody tr:hover { background:rgba(255, 228, 241, .24); }
    .badge { display:inline-flex; align-items:center; min-height:28px; border-radius:999px; padding:3px 10px; background:#eef2ff; color:#3730a3; font-size:.82rem; font-weight:900; white-space:nowrap; }
    .badge-draft { background:var(--surface-tint); color:#92400e; }
    .badge-published { background:var(--accent-2-soft); color:#047857; }
    .wide { grid-column:1 / -1; overflow-x:auto; }
    @media (max-width: 900px) {
      .wrap { width:min(100% - 22px, 1240px); }
      header .wrap { align-items:flex-start; flex-direction:column; }
      main.wrap { padding-top:18px; }
      .status, .grid, .field-grid, .range-line { grid-template-columns:1fr; }
      button, .button { width:100%; }
      .actions { width:100%; }
      .actions form { flex:1 1 100%; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior:auto !important; transition:none !important; }
    }
    """


def render_editor_page(
    *,
    rel_file: str,
    content: str,
    kind: str,
    title: str,
    site_route: str = "",
    suffix: str = "",
    is_new_post: bool = False,
    message: CommandResult | None = None,
) -> str:
    status_html = ""
    if message:
        status_html = html_escape(message.output or "完成。")
    preview_base = get_preview_url().rstrip("/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)} | 博客控制面板</title>
  <style>
    {base_panel_css()}
    body {{ height:100vh; overflow:hidden; }}
    header {{ position:static; }}
    .editor-shell {{ display:grid; grid-template-columns:minmax(0,1.04fr) minmax(380px,.96fr); gap:16px; height:calc(100vh - 102px); padding:0 16px 16px; }}
    .editor-pane, .preview-pane {{ min-width:0; min-height:0; display:flex; flex-direction:column; overflow:hidden; border:1px solid rgba(234, 221, 231, .9); border-radius:24px; box-shadow:var(--shadow); }}
    .editor-pane {{ background:#12162b; }}
    .editor-toolbar {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px; padding:14px; border-bottom:1px solid rgba(255,255,255,.1); background:linear-gradient(135deg,#171b34,#241a32); color:#f8fafc; }}
    .editor-toolbar code {{ border-radius:999px; background:rgba(255,255,255,.08); color:#fbcfe8; padding:3px 9px; }}
    .editor-toolbar .compact {{ margin:0; color:#e8edf8; }}
    .editor-toolbar input[type="file"] {{ width:auto; max-width:280px; min-height:40px; border-color:rgba(255,255,255,.16); background:rgba(255,255,255,.08); color:#e8edf8; }}
    .editor-toolbar .button, .editor-toolbar button {{ min-height:38px; }}
    .editor-toolbar .ghost {{ border-color:rgba(255,255,255,.14); background:rgba(255,255,255,.1); color:#fbcfe8; }}
    .editor-status {{ margin-left:auto; color:#cbd5e1; font-size:.92rem; }}
    .editor-status.is-dirty {{ color:#fde68a; }}
    .editor-metrics {{ border:1px solid rgba(255,255,255,.12); border-radius:999px; background:rgba(255,255,255,.07); color:#dbeafe; padding:3px 9px; font-size:.84rem; white-space:nowrap; }}
    #restore-draft-button[hidden] {{ display:none; }}
    #source-editor {{ flex:1; width:100%; min-height:0; border:0; border-radius:0; background:#101426; color:#f8fafc; padding:22px; font:15px/1.65 Consolas, "Cascadia Mono", "Microsoft YaHei", monospace; resize:none; outline:none; tab-size:2; caret-color:#f472b6; }}
    .preview-pane {{ background:#fff; }}
    .preview-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:16px 20px; border-bottom:1px solid rgba(234, 221, 231, .86); background:rgba(255,250,253,.86); }}
    .preview-body {{ flex:1; overflow:auto; padding:28px; background:#fff; }}
    .preview-body img {{ max-width:100%; border-radius:14px; }}
    .article-preview {{ max-width:760px; margin:0 auto; }}
    .article-cover {{ width:100%; aspect-ratio:2 / 1; object-fit:cover; margin-bottom:22px; box-shadow:var(--shadow-soft); }}
    .article-title {{ font-size:clamp(2rem, 5vw, 3.6rem); line-height:1.1; margin-bottom:10px; text-align:center; }}
    .article-meta, .article-description {{ color:var(--muted); text-align:center; }}
    .article-tags {{ display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin:14px 0 24px; }}
    .article-tag {{ border-radius:999px; background:var(--accent-soft); color:var(--accent-strong); padding:3px 11px; font-size:.9rem; font-weight:800; }}
    .article-divider {{ border:0; border-top:1px solid var(--line); margin:22px 0; }}
    .preview-body pre {{ max-height:none; }}
    .preview-body iframe {{ width:100%; min-height:70vh; border:1px solid var(--line); border-radius:16px; background:#fff; }}
    .site-preview-frame {{ height:100%; min-height:0 !important; border:0 !important; border-radius:0 !important; }}
    .preview-body table {{ margin:1rem 0; }}
    .preview-body blockquote {{ margin:1rem 0; padding-left:1rem; border-left:4px solid var(--accent); color:var(--muted); }}
    @media (max-width: 980px) {{
      body {{ height:auto; overflow:auto; }}
      .editor-shell {{ grid-template-columns:1fr; height:auto; }}
      #source-editor {{ min-height:54vh; }}
      .editor-pane {{ border-right:0; }}
      .preview-pane {{ min-height:60vh; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <div>
        <h1>{html_escape(title)}</h1>
        <p class="muted">{html_escape(rel_file if rel_file != "__new_post__" else "新文章，首次保存后会生成文件")}</p>
      </div>
      <div class="actions">
        <a class="button secondary" href="/">返回面板</a>
        <a class="button" href="{preview_base}/" target="_blank">打开预览</a>
      </div>
    </div>
  </header>
  <main class="editor-shell">
    <section class="editor-pane">
      <div class="editor-toolbar">
        <button id="save-button" type="button">保存</button>
        <label class="compact">
          <input id="image-upload" type="file" accept=".jpg,.jpeg,.png,.webp,.avif,.gif" multiple>
        </label>
        <button class="ghost" id="upload-button" type="button">插入图片</button>
        <span>类型：<code id="file-kind">{html_escape(kind)}</code></span>
        <button class="ghost" id="restore-draft-button" type="button" hidden>Restore draft</button>
        <span class="editor-status" id="editor-status">{status_html}</span>
        <span class="editor-metrics" id="editor-metrics"></span>
      </div>
      <textarea id="source-editor" spellcheck="false">{html_escape(content)}</textarea>
    </section>
    <section class="preview-pane">
      <div class="preview-head">
        <h2>预览</h2>
        <span class="muted" id="preview-kind">{html_escape(kind)}</span>
      </div>
      <div class="preview-body" id="preview"></div>
    </section>
  </main>
  <script>
    let currentFile = {json.dumps(rel_file, ensure_ascii=False)};
    const suffix = {json.dumps(suffix, ensure_ascii=False)};
    const kind = {json.dumps(kind, ensure_ascii=False)};
    const siteRoute = {json.dumps(site_route, ensure_ascii=False)};
    const previewBase = {json.dumps(preview_base, ensure_ascii=False)};
    const isNewPost = {json.dumps(is_new_post)};
    const csrfToken = {json.dumps(CSRF_TOKEN)};
    const editor = document.getElementById('source-editor');
    const preview = document.getElementById('preview');
    const status = document.getElementById('editor-status');
    const metrics = document.getElementById('editor-metrics');
    const restoreDraftButton = document.getElementById('restore-draft-button');
    const fileKind = document.getElementById('file-kind');
    const draftPrefix = 'blog-panel-source-draft:v1:';
    let savedSource = editor.value;
    let autosaveTimer = null;
    let currentDraftKey = draftKey();

    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, (char) => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }}[char]));
    }}

    function draftKey() {{
      return draftPrefix + (currentFile || '__new_post__') + ':' + suffix;
    }}

    function countSource(value) {{
      const cjkChars = value.match(/[\\u3400-\\u9fff]/g) || [];
      const latinWords = value.match(/[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)*/g) || [];
      return {{
        chars: Array.from(value).length,
        words: cjkChars.length + latinWords.length,
      }};
    }}

    function readDraft(key = currentDraftKey) {{
      try {{
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : null;
      }} catch {{
        return null;
      }}
    }}

    function writeDraft() {{
      if (editor.value === savedSource) {{
        clearDraft(currentDraftKey);
        return;
      }}
      try {{
        localStorage.setItem(currentDraftKey, JSON.stringify({{
          content: editor.value,
          file: currentFile,
          suffix,
          updatedAt: Date.now(),
        }}));
      }} catch {{}}
    }}

    function clearDraft(key = currentDraftKey) {{
      try {{
        localStorage.removeItem(key);
      }} catch {{}}
    }}

    function updateDraftRestore() {{
      const draft = readDraft();
      restoreDraftButton.hidden = !(draft && draft.content && draft.content !== editor.value);
    }}

    function updateEditorMeta(message = '') {{
      const counts = countSource(editor.value);
      metrics.textContent = 'Chars ' + counts.chars + ' / Words ' + counts.words;
      const dirty = editor.value !== savedSource;
      status.classList.toggle('is-dirty', dirty);
      if (message) {{
        status.textContent = message;
      }} else {{
        status.textContent = dirty ? 'Unsaved edits' : 'Saved';
      }}
    }}

    function queueAutosave() {{
      window.clearTimeout(autosaveTimer);
      autosaveTimer = window.setTimeout(() => {{
        writeDraft();
        updateDraftRestore();
      }}, 600);
    }}

    function handleEditorChange(message = '') {{
      renderPreview();
      queueAutosave();
      updateEditorMeta(message);
    }}

    function inlineMarkdown(value) {{
      let text = escapeHtml(value);
      text = text.replace(/!\\[([^\\]]*)\\]\\(([^)]+)\\)/g, '<img src="$2" alt="$1">');
      text = text.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
      text = text.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
      return text;
    }}

    function parseFrontmatter(source) {{
      const match = source.match(/^---\\s*\\n([\\s\\S]*?)\\n---\\s*/);
      if (!match) return {{ data: {{}}, body: source }};
      const data = {{}};
      for (const rawLine of match[1].split('\\n')) {{
        const index = rawLine.indexOf(':');
        if (index === -1) continue;
        const key = rawLine.slice(0, index).trim();
        let value = rawLine.slice(index + 1).trim();
        value = value.replace(/^['"]|['"]$/g, '');
        if (value.startsWith('[') && value.endsWith(']')) {{
          data[key] = value.slice(1, -1).split(',').map((item) => item.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
        }} else {{
          data[key] = value;
        }}
      }}
      return {{ data, body: source.slice(match[0].length) }};
    }}

    function resolvePreviewPath(path) {{
      if (!path) return '';
      if (/^(https?:)?\\/\\//.test(path) || path.startsWith('/')) return path;
      if (!currentFile || currentFile === '__new_post__') return path;
      const stack = currentFile.split('/').slice(0, -1);
      for (const part of path.split('/')) {{
        if (!part || part === '.') continue;
        if (part === '..') stack.pop();
        else stack.push(part);
      }}
      return '/preview_asset/' + stack.join('/');
    }}

    function renderMarkdownBody(body) {{
      const lines = body.split('\\n');
      const html = [];
      let inCode = false;
      let codeLines = [];
      let inList = false;
      for (const line of lines) {{
        if (line.trim().startsWith('```')) {{
          if (inCode) {{
            html.push('<pre><code>' + escapeHtml(codeLines.join('\\n')) + '</code></pre>');
            codeLines = [];
            inCode = false;
          }} else {{
            if (inList) {{ html.push('</ul>'); inList = false; }}
            inCode = true;
          }}
          continue;
        }}
        if (inCode) {{
          codeLines.push(line);
          continue;
        }}
        if (/^\\s*-\\s+/.test(line)) {{
          if (!inList) {{ html.push('<ul>'); inList = true; }}
          html.push('<li>' + inlineMarkdown(line.replace(/^\\s*-\\s+/, '')) + '</li>');
          continue;
        }}
        if (inList) {{ html.push('</ul>'); inList = false; }}
        if (!line.trim()) {{
          html.push('');
        }} else if (line.startsWith('### ')) {{
          html.push('<h3>' + inlineMarkdown(line.slice(4)) + '</h3>');
        }} else if (line.startsWith('## ')) {{
          html.push('<h2>' + inlineMarkdown(line.slice(3)) + '</h2>');
        }} else if (line.startsWith('# ')) {{
          html.push('<h1>' + inlineMarkdown(line.slice(2)) + '</h1>');
        }} else if (line.startsWith('> ')) {{
          html.push('<blockquote>' + inlineMarkdown(line.slice(2)) + '</blockquote>');
        }} else {{
          html.push('<p>' + inlineMarkdown(line) + '</p>');
        }}
      }}
      if (inList) html.push('</ul>');
      if (inCode) html.push('<pre><code>' + escapeHtml(codeLines.join('\\n')) + '</code></pre>');
      return html.join('\\n');
    }}

    function renderMarkdown(source) {{
      const parsed = parseFrontmatter(source);
      const data = parsed.data;
      const title = data.title || '未命名文章';
      const description = data.description || '';
      const pubDate = data.pubDate || '';
      const updatedDate = data.updatedDate || '';
      const tags = Array.isArray(data.tags) ? data.tags : [];
      const heroImage = resolvePreviewPath(data.heroImage || '');
      const cover = heroImage ? '<img class="article-cover" src="' + escapeHtml(heroImage) + '" alt="' + escapeHtml(title) + ' 封面">' : '';
      const tagHtml = tags.length ? '<div class="article-tags">' + tags.map((tag) => '<span class="article-tag">' + escapeHtml(tag) + '</span>').join('') + '</div>' : '';
      const updatedHtml = updatedDate ? ' · 更新于 ' + escapeHtml(updatedDate) : '';
      preview.innerHTML = `
        <article class="article-preview">
          ${{cover}}
          <p class="article-meta">${{escapeHtml(pubDate)}}${{updatedHtml}}</p>
          <h1 class="article-title">${{escapeHtml(title)}}</h1>
          ${{description ? '<p class="article-description">' + escapeHtml(description) + '</p>' : ''}}
          ${{tagHtml}}
          <hr class="article-divider">
          <div class="article-body">${{renderMarkdownBody(parsed.body)}}</div>
        </article>
      `;
    }}

    function renderPreview() {{
      const source = editor.value;
      if (siteRoute) {{
        const url = previewBase + siteRoute + (siteRoute.includes('?') ? '&' : '?') + 'panelPreview=' + Date.now();
        preview.innerHTML = `
          <iframe class="site-preview-frame" src="${{url}}"></iframe>
          <p class="muted">这里显示的是 Astro 本地预览服务。如果没有画面，请先回到控制面板点击“启动预览”。</p>
        `;
        return;
      }}
      if (['md', 'mdx'].includes(kind)) {{
        renderMarkdown(source);
        return;
      }}
      if (kind === 'json') {{
        try {{
          preview.innerHTML = '<pre><code>' + escapeHtml(JSON.stringify(JSON.parse(source), null, 2)) + '</code></pre>';
        }} catch (error) {{
          preview.innerHTML = '<pre><code>' + escapeHtml(error.message + '\\n\\n' + source) + '</code></pre>';
        }}
        return;
      }}
      if (['html', 'svg'].includes(kind)) {{
        preview.innerHTML = '<iframe sandbox="allow-same-origin" srcdoc="' + escapeHtml(source) + '"></iframe>';
        return;
      }}
      preview.innerHTML = '<pre><code>' + escapeHtml(source) + '</code></pre>';
    }}

    function insertAtCursor(text) {{
      const start = editor.selectionStart ?? editor.value.length;
      const end = editor.selectionEnd ?? editor.value.length;
      const before = editor.value.slice(0, start);
      const after = editor.value.slice(end);
      const insertion = (before && !before.endsWith('\\n') ? '\\n\\n' : '') + text + (after && !text.endsWith('\\n') ? '\\n\\n' : '');
      editor.value = before + insertion + after;
      const cursor = before.length + insertion.length;
      editor.focus();
      editor.setSelectionRange(cursor, cursor);
      handleEditorChange();
    }}

    async function saveSource() {{
      status.textContent = '保存中...';
      const previousDraftKey = currentDraftKey;
      const body = new URLSearchParams();
      body.set('file', currentFile);
      body.set('content', editor.value);
      body.set('suffix', suffix);
      body.set('_csrf', csrfToken);
      const response = await fetch('/action/save_source', {{ method: 'POST', body }});
      const text = await response.text();
      status.textContent = text;
      if (!response.ok) {{
        updateEditorMeta(text || 'Save failed');
        return;
      }}
      const match = text.match(/^已保存：(.+)$/);
      if (match) {{
        currentFile = match[1];
        if (fileKind) fileKind.textContent = currentFile.split('.').pop() || kind;
        const editPath = currentFile.startsWith('site/src/content/blog/') ? '/post/edit' : '/file/edit';
        history.replaceState(null, '', editPath + '?file=' + encodeURIComponent(currentFile));
        if (siteRoute) renderPreview();
      }}
      savedSource = editor.value;
      clearDraft(previousDraftKey);
      currentDraftKey = draftKey();
      clearDraft(currentDraftKey);
      updateDraftRestore();
      updateEditorMeta(text || 'Saved');
    }}

    async function uploadImages() {{
      const input = document.getElementById('image-upload');
      if (!input.files.length) {{
        status.textContent = '请选择图片。';
        return;
      }}
      status.textContent = '上传中...';
      const body = new FormData();
      body.set('_csrf', csrfToken);
      for (const file of input.files) body.append('images', file);
      const response = await fetch('/action/upload_editor_images', {{ method: 'POST', body }});
      const text = await response.text();
      if (!response.ok || !text.startsWith('![')) {{
        status.textContent = text;
        return;
      }}
      insertAtCursor(text);
      input.value = '';
      status.textContent = '图片已插入到光标位置。';
    }}

    document.getElementById('save-button').addEventListener('click', saveSource);
    document.getElementById('upload-button').addEventListener('click', uploadImages);
    restoreDraftButton.addEventListener('click', () => {{
      const draft = readDraft();
      if (!draft || typeof draft.content !== 'string') return;
      editor.value = draft.content;
      handleEditorChange('Restored local draft');
      restoreDraftButton.hidden = true;
      editor.focus();
    }});
    editor.addEventListener('input', () => handleEditorChange());
    editor.addEventListener('keydown', (event) => {{
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {{
        event.preventDefault();
        saveSource();
      }}
      if (event.key === 'Tab') {{
        event.preventDefault();
        insertAtCursor('  ');
      }}
    }});
    window.addEventListener('beforeunload', (event) => {{
      if (editor.value === savedSource) return;
      event.preventDefault();
      event.returnValue = '';
    }});
    updateDraftRestore();
    renderPreview();
    updateEditorMeta(status.textContent.trim());
  </script>
</body>
</html>"""


def render_page(message: CommandResult | None = None, edit_file: str = "") -> str:
    posts = list_posts()
    friends = read_friends()
    home = read_home()
    navigation = read_navigation()
    footer = read_footer()
    theme = read_theme()
    templates = list_post_templates()
    editable_files = list_editable_files()
    home_section = home["sections"][0] if home.get("sections") else {}
    git_status = get_git_status()
    preview_url, preview_running = get_preview_state()
    deps_ready = node_modules_ready()
    site_url = get_site_url()
    drafts = [post for post in posts if post["draft"]]
    edit_post = get_post_for_edit(edit_file)

    message_html = ""
    if message:
        status_class = "ok" if message.code == 0 else "bad"
        message_html = f"""
        <section class="panel result {status_class}">
          <h2>操作结果</h2>
          <pre>{html_escape(message.output or '完成。')}</pre>
        </section>
        """

    post_options = "\n".join(
        f'<option value="{html_escape(post["file"])}">{html_escape(post["title"])} ({html_escape(post["name"])})</option>'
        for post in drafts
    )
    template_options = "\n".join(
        f'<option value="{html_escape(template["file"])}">{html_escape(template["title"])} ({html_escape(template["kind"].upper())})</option>'
        for template in templates
    )
    edit_options = "\n".join(
        f'<option value="{html_escape(post["file"])}" {"selected" if edit_post and post["file"] == edit_post["file"] else ""}>{html_escape(post["title"])} ({html_escape(post["name"])})</option>'
        for post in posts
    )
    friend_rows = "\n".join(
        f"""
        <tr>
          <td>{html_escape(friend.get('name', ''))}</td>
          <td><a href="{html_escape(friend.get('url', ''))}" target="_blank">{html_escape(friend.get('url', ''))}</a></td>
          <td>{html_escape(friend.get('description', ''))}</td>
          <td>
            <form method="post" action="/action/delete_friend">
              <input type="hidden" name="url" value="{html_escape(friend.get('url', ''))}">
              <button class="ghost danger" type="submit">删除</button>
            </form>
          </td>
        </tr>
        """
        for friend in friends
    )
    navigation_row_parts: list[str] = []
    for index, item in enumerate(navigation):
        page_file = page_file_for_href(str(item.get("href", "")))
        edit_link = (
            f'<a class="button ghost" href="/file/edit?file={quote(page_file)}">编辑页面</a>'
            if page_file
            else '<span class="muted">无对应页面</span>'
        )
        navigation_row_parts.append(
            f"""
        <tr>
          <td><input name="order_{index}" type="number" min="1" value="{index + 1}"></td>
          <td><input name="label_{index}" required value="{html_escape(item.get('label', ''))}"></td>
          <td><input name="href_{index}" required value="{html_escape(item.get('href', ''))}" placeholder="/blog"></td>
          <td><label class="compact"><input type="checkbox" name="enabled_{index}" {'checked' if item.get('enabled', True) else ''}> 显示</label></td>
          <td>{edit_link}</td>
          <td><label class="compact"><input type="checkbox" name="delete_{index}"> 删除</label></td>
        </tr>
        """
        )
    navigation_rows = "\n".join(navigation_row_parts)
    edit_form_html = ""
    if edit_file and not edit_post:
        edit_form_html = """
      <div class="panel wide result bad">
        <h2>编辑文章</h2>
        <pre>没有找到要编辑的文章。</pre>
      </div>
        """
    elif edit_post:
        edit_form_html = f"""
      <div class="panel wide" id="edit-post">
        <h2>编辑文章</h2>
        <form method="post" action="/action/save_post" enctype="multipart/form-data">
          <input type="hidden" name="file" value="{html_escape(edit_post['file'])}">
          <label>标题</label>
          <input name="title" required maxlength="80" value="{html_escape(edit_post['title'])}">
          <label>摘要</label>
          <textarea name="description" required maxlength="180">{html_escape(edit_post['description'])}</textarea>
          <label>标签（用逗号分隔）</label>
          <input name="tags" value="{html_escape(edit_post['tags'])}">
          <label>发布日期</label>
          <input name="pubDate" type="date" value="{html_escape(edit_post['pubDate'])}">
          <label>更新日期（可选）</label>
          <input name="updatedDate" type="date" value="{html_escape(edit_post['updatedDate'])}">
          <label>封面图路径</label>
          <input name="heroImage" value="{html_escape(edit_post['heroImage'])}">
          <label>上传新封面图（jpg、png、webp、avif）</label>
          <input name="heroImageFile" type="file" accept=".jpg,.jpeg,.png,.webp,.avif,image/jpeg,image/png,image/webp,image/avif">
          <label><input style="width:auto" type="checkbox" name="draft" {'checked' if edit_post['draft'] else ''}> 保存为草稿</label>
          <label>正文</label>
          <textarea name="body" class="body-editor">{html_escape(edit_post['body'])}</textarea>
          <div class="actions">
            <button type="submit">保存文章</button>
            <a class="button secondary" href="/">关闭编辑</a>
          </div>
        </form>
      </div>
        """
    post_row_parts: list[str] = []
    for post in posts:
        share_url = f"{site_url}/blog/{post['name'].rsplit('.', 1)[0]}/"
        visibility_button = (
            f"""
            <form method="post" action="/action/set_post_visibility">
              <input type="hidden" name="file" value="{html_escape(post['file'])}">
              <input type="hidden" name="visible" value="true">
              <button class="ghost" type="submit">显示</button>
            </form>
            """
            if post["draft"]
            else f"""
            <form method="post" action="/action/set_post_visibility">
              <input type="hidden" name="file" value="{html_escape(post['file'])}">
              <input type="hidden" name="visible" value="false">
              <button class="ghost" type="submit">取消发布</button>
            </form>
            """
        )
        share_cell = (
            f"""
            <a class="button ghost" href="{html_escape(share_url)}" target="_blank" rel="noopener noreferrer">打开</a>
            <button class="ghost copy-link" type="button" data-url="{html_escape(share_url)}">复制</button>
            """
            if not post["draft"]
            else '<span class="muted">隐藏后不能分享</span>'
        )
        post_row_parts.append(
            f"""
        <tr>
          <td><span class="badge {'badge-draft' if post['draft'] else 'badge-published'}">{'草稿' if post['draft'] else '已发布'}</span></td>
          <td>{html_escape(post['title'])}</td>
          <td>{html_escape(post['date'])}</td>
          <td>{html_escape(', '.join(post['tags']))}</td>
          <td>{html_escape(post['file'])}</td>
          <td><div class="actions">{visibility_button}<a class="button ghost" href="/post/edit?file={quote(post['file'])}">编辑</a><form method="post" action="/action/save_post_template"><input type="hidden" name="file" value="{html_escape(post['file'])}"><button class="ghost" type="submit">存为模板</button></form></div></td>
          <td><div class="actions">{share_cell}</div></td>
        </tr>
        """
        )
    post_rows = "\n".join(post_row_parts)
    image_post_options = "\n".join(
        f'<option value="{html_escape(post["file"])}">{html_escape(post["title"])} ({html_escape(post["name"])})</option>'
        for post in posts
    )
    file_options = "\n".join(
        f'<option value="{html_escape(item["file"])}">{html_escape(item["file"])}</option>'
        for item in editable_files
    )
    font_choices = BUILTIN_FONT_OPTIONS + [
        {
            "id": str(font.get("id", "")),
            "label": f"自定义：{font.get('label') or font.get('family') or font.get('id')}",
        }
        for font in theme.get("customFonts", [])
        if isinstance(font, dict) and font.get("id")
    ]
    def font_options(selected: Any) -> str:
        return "\n".join(
            f'<option value="{html_escape(item["id"])}" {"selected" if item["id"] == selected else ""}>{html_escape(item["label"])}</option>'
            for item in font_choices
        )

    body_font_options = font_options(theme.get("bodyFont"))
    heading_font_options = font_options(theme.get("headingFont"))
    nav_font_options = font_options(theme.get("navFont", theme.get("bodyFont")))
    home_title_font_options = font_options(theme.get("homeTitleFont", theme.get("headingFont")))
    home_text_font_options = font_options(theme.get("homeTextFont", theme.get("bodyFont")))
    post_title_font_options = font_options(theme.get("postTitleFont", theme.get("headingFont")))
    post_body_font_options = font_options(theme.get("postBodyFont", theme.get("bodyFont")))
    footer_font_options = font_options(theme.get("footerFont", theme.get("bodyFont")))
    custom_font_rows = "\n".join(
        f'<li>{html_escape(font.get("label") or font.get("family") or font.get("id"))} <span class="muted">{html_escape(font.get("url", ""))}</span></li>'
        for font in theme.get("customFonts", [])
        if isinstance(font, dict)
    )
    douyin_preview_class = "" if footer.get("douyinHref") else " is-empty"
    douyin_preview_href = html_escape(footer.get("douyinHref") or "#")
    bilibili_preview_class = "" if footer.get("bilibiliHref") else " is-empty"
    bilibili_preview_href = html_escape(footer.get("bilibiliHref") or "#")
    draft_metric_class = "is-warn" if drafts else "is-ok"
    preview_metric_class = "is-ok" if preview_running else "is-warn"
    deps_metric_class = "is-ok" if deps_ready else "is-warn"
    embedded_preview_html = (
        f'<iframe src="{preview_url}" title="网站实时预览"></iframe>'
        if preview_running
        else '<div class="preview-placeholder">预览服务还没启动。点击上面的“启动预览”后，这里会显示网站首页。</div>'
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>博客控制面板</title>
  <style>
    {base_panel_css()}
    .panel-nav {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 18px; padding:8px; border:1px solid rgba(234, 221, 231, .94); border-radius:999px; background:rgba(255,255,255,.72); box-shadow:var(--shadow-soft); backdrop-filter:blur(12px); }}
    .panel-nav a {{ flex:1 1 128px; border-radius:999px; padding:10px 14px; color:#5f4556; text-align:center; text-decoration:none; font-weight:900; }}
    .panel-nav a:hover {{ background:var(--accent-soft); color:var(--accent-strong); }}
    .quick-actions {{ position:relative; overflow:hidden; margin-bottom:20px; padding:24px; background:linear-gradient(135deg, rgba(255,255,255,.92) 0%, rgba(255,228,241,.82) 46%, rgba(217,248,238,.9) 100%); }}
    .quick-actions::after {{ position:absolute; right:-90px; top:-120px; width:280px; height:280px; border:1px solid rgba(239,79,154,.22); border-radius:999px; content:""; }}
    .quick-actions > * {{ position:relative; z-index:1; }}
    .quick-actions-head {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:12px; }}
    .quick-actions .actions {{ margin-top:16px; }}
    .quick-actions form {{ margin:0; }}
    .commit-line {{ display:grid; grid-template-columns:minmax(220px,1fr) auto; gap:12px; align-items:end; margin-top:16px; padding-top:16px; border-top:1px solid rgba(234, 221, 231, .72); }}
    .dashboard-preview {{ margin-bottom:20px; overflow:hidden; padding:0; }}
    .dashboard-preview-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:18px 20px; border-bottom:1px solid rgba(234, 221, 231, .86); background:rgba(255,250,253,.76); }}
    .dashboard-preview-head h2 {{ margin:0; }}
    .dashboard-preview iframe {{ display:block; width:100%; min-height:540px; border:0; background:#fff; }}
    .preview-placeholder {{ min-height:260px; display:grid; place-items:center; padding:32px; color:var(--muted); text-align:center; background:radial-gradient(circle at 50% 25%, rgba(255,228,241,.95), transparent 15rem), linear-gradient(135deg,#fffafd,#f4fbff); }}
    .footer-icon-preview {{ display:flex; align-items:center; gap:12px; margin:14px 0 4px; padding:14px; border:1px dashed #cbd5e1; border-radius:12px; background:#f8fafc; }}
    .footer-icon-preview strong {{ margin-right:auto; color:#334155; }}
    .panel-social {{ width:36px; height:36px; display:inline-flex; align-items:center; justify-content:center; border:1px solid #dbe4ef; border-radius:999px; background:#fff; color:#23304b; text-decoration:none; transition:transform .18s ease, box-shadow .18s ease; }}
    .panel-social:hover {{ transform:translateY(-1px); box-shadow:0 8px 22px rgba(15,23,42,.12); }}
    .panel-social.is-empty {{ opacity:.38; filter:grayscale(1); pointer-events:none; }}
    .panel-social svg {{ width:18px; height:18px; display:block; }}
    .panel-social.douyin {{ color:#111827; }}
    .panel-social.bilibili {{ color:#00aeec; }}
    @media (max-width: 900px) {{ .commit-line {{ grid-template-columns:1fr; }} .quick-actions-head, .dashboard-preview-head {{ align-items:flex-start; flex-direction:column; }} .panel-nav {{ border-radius:20px; }} .dashboard-preview iframe {{ min-height:420px; }} }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <div>
        <p class="eyebrow">Local Blog Studio</p>
        <h1>博客控制面板</h1>
        <p class="muted">本地工具，只操作 D:\\Blog 里的静态博客文件。</p>
      </div>
      <div class="actions">
        <a class="button" href="{preview_url}" target="_blank">打开预览</a>
        <a class="button secondary" href="/" aria-current="page">刷新面板</a>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section class="panel quick-actions" id="quick-actions">
      <div class="quick-actions-head">
        <div>
          <h2>预览、构建和发布</h2>
          <p class="muted">最常用的启动预览、构建检查、推送上线都放在这里，打开控制面板就能直接操作。</p>
        </div>
        <a class="button ghost" href="{preview_url}" target="_blank">打开网站预览</a>
      </div>
      <div class="actions">
        <form method="post" action="/action/check_requirements"><button class="ghost" type="submit">检查环境</button></form>
        <form method="post" action="/action/install_dependencies"><button class="secondary" type="submit">安装/更新依赖</button></form>
        <form method="post" action="/action/start_preview"><button type="submit">启动预览</button></form>
        <form method="post" action="/action/stop_preview"><button class="secondary" type="submit">停止预览</button></form>
        <form method="post" action="/action/build"><button type="submit">构建检查</button></form>
      </div>
      <form method="post" action="/action/update_blog" class="commit-line">
        <div>
          <label>提交说明</label>
          <input name="message" value="update blog">
        </div>
        <button type="submit">构建并推送</button>
      </form>
    </section>
    {message_html}
    <nav class="panel-nav" aria-label="控制面板分区">
      <a href="#quick-actions">预览发布</a>
      <a href="#writing-section">文章写作</a>
      <a href="#pages-section">页面导航</a>
      <a href="#appearance-section">外观底部</a>
      <a href="#data-section">友链数据</a>
    </nav>
    <section class="status">
      <div class="metric"><strong>{len(posts)}</strong><span>文章总数</span><small>包含已发布和草稿</small></div>
      <div class="metric {draft_metric_class}"><strong>{len(drafts)}</strong><span>草稿</span><small>写完后可一键发布</small></div>
      <div class="metric"><strong>{len(friends)}</strong><span>友链</span><small>朋友们的小入口</small></div>
      <div class="metric {preview_metric_class}"><strong>{'运行中' if preview_running else '未启动'}</strong><span>本地预览</span><small>保存后对照效果</small></div>
      <div class="metric {deps_metric_class}"><strong>{'已安装' if deps_ready else '未安装'}</strong><span>项目依赖</span><small>构建前需要就绪</small></div>
    </section>
    <section class="panel dashboard-preview" id="site-preview">
      <div class="dashboard-preview-head">
        <div>
          <h2>网站预览</h2>
          <p class="muted">这里直接嵌入本地预览首页，方便你保存设置后马上对照效果。</p>
        </div>
        <a class="button ghost" href="{preview_url}" target="_blank">新窗口打开</a>
      </div>
      {embedded_preview_html}
    </section>
    <section class="grid">
      <div class="section-title" id="writing-section">
        <h2>文章写作</h2>
        <p>新建、编辑、发布、插图和文章显示控制都在这一组。</p>
      </div>
      <div class="panel">
        <h2>新建文章</h2>
        <form method="get" action="/post/new">
          <label>标题</label>
          <input name="title" required maxlength="80" placeholder="例如：今天把博客控制面板做起来">
          <label>摘要</label>
          <textarea name="description" required maxlength="180" placeholder="一句话说明这篇文章写什么"></textarea>
          <label>标签（用逗号分隔）</label>
          <input name="tags" placeholder="建站, 记录">
          <label>发布日期</label>
          <input name="pubDate" type="date" value="{date.today().isoformat()}">
          <label>文章模板</label>
          <select name="template">
            <option value="">空白模板</option>
            {template_options}
          </select>
          <span class="hint">模板来自 scripts/post_templates。第一次启动面板会自动用当前几篇文章生成模板；也可以在文章列表里点“存为模板”。</span>
          <label>格式</label>
          <select name="format"><option value="md">Markdown</option><option value="mdx">MDX</option></select>
          <span class="hint">选择模板时会优先使用模板自己的 md/mdx 格式。</span>
          <input type="hidden" name="draft" value="off">
          <label><input style="width:auto" type="checkbox" name="draft" value="on" checked> 先隐藏，不在网站显示</label>
          <div class="actions"><button type="submit">进入编辑器</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>发布草稿</h2>
        <p class="muted">把选中的文章从 draft: true 改成 draft: false。</p>
        <form method="post" action="/action/publish_post">
          <label>选择草稿</label>
          <select name="file" {'disabled' if not drafts else ''}>{post_options or '<option>暂无草稿</option>'}</select>
          <div class="actions"><button type="submit" {'disabled' if not drafts else ''}>发布这篇</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>当前模板</h2>
        <p class="muted">新建文章时可以从这些模板起步，打开编辑器后再改标题、正文和图片。</p>
        <ul>{''.join(f'<li>{html_escape(template["title"])} <span class="muted">{html_escape(template["name"])}</span></li>' for template in templates) or '<li class="muted">暂无模板，重启控制面板会从当前文章自动生成。</li>'}</ul>
      </div>
      <div class="panel">
        <h2>编辑已有文章</h2>
        <form method="get" action="/post/edit">
          <label>选择文章</label>
          <select name="file" {'disabled' if not posts else ''}>{edit_options or '<option>暂无文章</option>'}</select>
          <div class="actions"><button type="submit" {'disabled' if not posts else ''}>进入编辑器</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>编辑常用文件</h2>
        <form method="get" action="/file/edit">
          <label>选择文件</label>
          <select name="file" {'disabled' if not editable_files else ''}>{file_options or '<option>暂无可编辑文件</option>'}</select>
          <div class="actions"><button type="submit" {'disabled' if not editable_files else ''}>打开文件</button></div>
        </form>
      </div>
      {edit_form_html}
      <div class="section-title" id="pages-section">
        <h2>页面导航</h2>
        <p>这里管理导航栏显示、链接顺序，以及“关于我”等独立页面的编辑入口。</p>
      </div>
      <div class="panel wide" id="navigation">
        <h2>导航栏目</h2>
        <form method="post" action="/action/update_navigation">
          <table>
            <thead><tr><th>顺序</th><th>名称</th><th>链接</th><th>显示</th><th>页面内容</th><th>删除</th></tr></thead>
            <tbody>{navigation_rows}</tbody>
          </table>
          <h3>新增栏目</h3>
          <label>名称</label>
          <input name="new_label" placeholder="例如：作品">
          <label>链接</label>
          <input name="new_href" placeholder="/projects">
          <label>顺序</label>
          <input name="new_order" type="number" min="1" value="{len(navigation) + 1}">
          <label class="compact"><input type="checkbox" name="new_enabled" checked> 新栏目立即显示</label>
          <span class="hint">链接可以填站内路径，比如 /blog、/about，也可以填完整外链。改完后启动预览刷新页面即可看到导航变化。</span>
          <div class="actions"><button type="submit">保存导航栏目</button></div>
        </form>
      </div>
      <div class="section-title" id="appearance-section">
        <h2>外观、字体和底部</h2>
        <p>首页文案背景、各区域字体、网站底部和社交图标集中放在这里。</p>
      </div>
      <div class="panel wide" id="footer-settings">
        <h2>底部信息</h2>
        <form method="post" action="/action/update_footer">
          <label>版权行</label>
          <input name="copyright" value="{html_escape(footer.get('copyright', ''))}" placeholder="© {{year}} ztt. All rights reserved.">
          <span class="hint">可以使用 {{year}}，页面会自动替换成当前年份。</span>
          <label>说明文字</label>
          <input name="description" value="{html_escape(footer.get('description', ''))}">
          <label class="compact"><input type="checkbox" name="showRss" {'checked' if footer.get('showRss') else ''}> 显示 RSS 链接</label>
          <div class="field-grid">
            <div>
              <label>RSS 文字</label>
              <input name="rssLabel" value="{html_escape(footer.get('rssLabel', ''))}">
            </div>
            <div>
              <label>RSS 链接</label>
              <input name="rssHref" value="{html_escape(footer.get('rssHref', ''))}">
            </div>
          </div>
          <div class="field-grid">
            <div>
              <label>抖音主页链接</label>
              <input name="douyinHref" value="{html_escape(footer.get('douyinHref', ''))}" placeholder="https://www.douyin.com/user/...">
            </div>
            <div>
              <label>Bilibili 主页链接</label>
              <input name="bilibiliHref" value="{html_escape(footer.get('bilibiliHref', ''))}" placeholder="https://space.bilibili.com/...">
            </div>
          </div>
          <span class="hint">链接为空时不会显示对应图标；填写后底部会显示小图标并跳转到你的主页。</span>
          <div class="footer-icon-preview" aria-label="底部社交图标预览">
            <strong>图标预览</strong>
            <a class="panel-social douyin{douyin_preview_class}" href="{douyin_preview_href}" target="_blank" rel="noopener noreferrer" title="抖音">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path fill="currentColor" d="M14.4 3c.3 2.7 1.8 4.6 4.6 4.8v3.1a8 8 0 0 1-4.5-1.3v5.8c0 3.4-2.5 5.6-5.7 5.6A5.5 5.5 0 0 1 3 15.5c0-3.5 3-6 6.8-5.4v3.2c-2-.5-3.6.4-3.6 2.1 0 1.3 1 2.3 2.4 2.3 1.6 0 2.5-.9 2.5-2.8V3h3.3Z"/>
              </svg>
            </a>
            <a class="panel-social bilibili{bilibili_preview_class}" href="{bilibili_preview_href}" target="_blank" rel="noopener noreferrer" title="bilibili">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path fill="currentColor" d="M8.1 4.2 10 6.1h4l1.9-1.9a1 1 0 0 1 1.4 1.4L16.9 6H18a3 3 0 0 1 3 3v7.2a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V9a3 3 0 0 1 3-3h1.1L6.7 5.6a1 1 0 1 1 1.4-1.4ZM6 8.7c-.4 0-.8.4-.8.8v6.2c0 .5.4.8.8.8h12c.4 0 .8-.3.8-.8V9.5c0-.4-.4-.8-.8-.8H6Zm2.4 2.7c.6 0 1 .5 1 1v1.1a1 1 0 0 1-2 0v-1.1c0-.5.4-1 1-1Zm7.2 0c.6 0 1 .5 1 1v1.1a1 1 0 0 1-2 0v-1.1c0-.5.4-1 1-1Z"/>
              </svg>
            </a>
          </div>
          <span class="hint">灰色表示链接还没填；保存链接后，预览和正式网站底部都会显示可点击图标。</span>
          <div class="actions"><button type="submit">保存底部信息</button></div>
        </form>
      </div>
      <div class="panel wide" id="theme-fonts">
        <h2>字体设置</h2>
        <form method="post" action="/action/update_theme" enctype="multipart/form-data">
          <p class="muted">普通选项使用字体栈：访客电脑有这个字体就显示，没有就自动回退到可用字体。只有上传自定义字体时，字体文件才会跟着网站发布。</p>
          <div class="field-grid">
            <div>
              <label>全站正文字体</label>
              <select name="bodyFont">{body_font_options}</select>
            </div>
            <div>
              <label>标题字体</label>
              <select name="headingFont">{heading_font_options}</select>
            </div>
            <div>
              <label>导航栏字体</label>
              <select name="navFont">{nav_font_options}</select>
            </div>
            <div>
              <label>首页大标题字体</label>
              <select name="homeTitleFont">{home_title_font_options}</select>
            </div>
            <div>
              <label>首页说明文字字体</label>
              <select name="homeTextFont">{home_text_font_options}</select>
            </div>
            <div>
              <label>文章标题字体</label>
              <select name="postTitleFont">{post_title_font_options}</select>
            </div>
            <div>
              <label>文章正文字体</label>
              <select name="postBodyFont">{post_body_font_options}</select>
            </div>
            <div>
              <label>底部字体</label>
              <select name="footerFont">{footer_font_options}</select>
            </div>
          </div>
          <h3>上传自定义字体</h3>
          <label>字体名称</label>
          <input name="fontFamily" placeholder="例如：霞鹜文楷">
          <label>字体粗细</label>
          <select name="fontWeight">
            <option value="400">常规 400</option>
            <option value="500">中等 500</option>
            <option value="700">粗体 700</option>
          </select>
          <label>字体文件</label>
          <input name="fontFile" type="file" accept=".woff2,.woff,.ttf,.otf,font/*">
          <span class="hint">推荐上传 woff2 或 woff。中文字体可能有几 MB 到几十 MB，只在需要特殊字体时上传。</span>
          <label class="compact"><input type="checkbox" name="applyUploadedToBody"> 上传后应用到全站正文</label>
          <label class="compact"><input type="checkbox" name="applyUploadedToHeading"> 上传后应用到全站标题</label>
          <div class="actions"><button type="submit">保存字体设置</button></div>
        </form>
        <h3>已上传字体</h3>
        <ul>{custom_font_rows or '<li class="muted">暂无自定义字体</li>'}</ul>
      </div>
      <div class="panel wide" id="home-design">
        <h2>首页设计</h2>
        <form method="post" action="/action/update_home" enctype="multipart/form-data">
          <label>首页小标题</label>
          <input name="kicker" value="{html_escape(home.get('kicker', ''))}">
          <label>首页大标题</label>
          <input name="title" value="{html_escape(home.get('title', ''))}">
          <label>首页说明</label>
          <textarea name="description">{html_escape(home.get('description', ''))}</textarea>
          <label>主按钮文字</label>
          <input name="primaryLabel" value="{html_escape(home.get('primaryLabel', ''))}">
          <label>主按钮链接</label>
          <input name="primaryHref" value="{html_escape(home.get('primaryHref', ''))}">
          <label>副按钮文字</label>
          <input name="secondaryLabel" value="{html_escape(home.get('secondaryLabel', ''))}">
          <label>副按钮链接</label>
          <input name="secondaryHref" value="{html_escape(home.get('secondaryHref', ''))}">
          <label>右侧信息小标题</label>
          <input name="panelEyebrow" value="{html_escape(home.get('panelEyebrow', ''))}">
          <label>右侧信息标题</label>
          <input name="panelTitle" value="{html_escape(home.get('panelTitle', ''))}">
          <label>右侧信息说明</label>
          <textarea name="panelText">{html_escape(home.get('panelText', ''))}</textarea>
          <label>当前首页背景图路径</label>
          <input name="heroBackground" value="{html_escape(home.get('heroBackground', ''))}" placeholder="/uploads/home/background.webp">
          <label>上传首页背景图（jpg、png、webp、avif、gif、svg）</label>
          <input name="heroBackgroundFile" type="file" accept=".jpg,.jpeg,.png,.webp,.avif,.gif">
          <h3>透明度</h3>
          <div class="field-grid">
            <div>
              <label>背景左侧白色遮罩</label>
              <div class="range-line">
                <input name="heroOverlayStart" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('heroOverlayStart', 0.72))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('heroOverlayStart', 0.72))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='heroOverlayStart'">
              </div>
            </div>
            <div>
              <label>背景右侧白色遮罩</label>
              <div class="range-line">
                <input name="heroOverlayEnd" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('heroOverlayEnd', 0.42))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('heroOverlayEnd', 0.42))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='heroOverlayEnd'">
              </div>
            </div>
            <div>
              <label>当前状态白色遮罩</label>
              <div class="range-line">
                <input name="heroPanelOpacity" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('heroPanelOpacity', 0.82))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('heroPanelOpacity', 0.82))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='heroPanelOpacity'">
              </div>
            </div>
            <div>
              <label>主按钮透明度</label>
              <div class="range-line">
                <input name="primaryButtonOpacity" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('primaryButtonOpacity', 1.0))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('primaryButtonOpacity', 1.0))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='primaryButtonOpacity'">
              </div>
            </div>
            <div>
              <label>副按钮透明度</label>
              <div class="range-line">
                <input name="secondaryButtonOpacity" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('secondaryButtonOpacity', 0.86))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('secondaryButtonOpacity', 0.86))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='secondaryButtonOpacity'">
              </div>
            </div>
          </div>
          <span class="hint">数值越低越透明。背景遮罩太低会影响文字可读性，建议左侧 0.55-0.8、右侧 0.25-0.55。</span>
          <label><input style="width:auto" type="checkbox" name="clearHeroBackground"> 清空首页背景图</label>
          <label><input style="width:auto" type="checkbox" name="showLatestPosts" {'checked' if home.get('showLatestPosts') else ''}> 显示“最近文章”栏目</label>
          <label><input style="width:auto" type="checkbox" name="showTopics" {'checked' if home.get('showTopics') else ''}> 显示“正在整理的主题”栏目</label>
          <h3>自定义首页栏目</h3>
          <label><input style="width:auto" type="checkbox" name="sectionEnabled" {'checked' if home_section.get('enabled') else ''}> 显示这个栏目</label>
          <label><input style="width:auto" type="checkbox" name="deleteSection"> 删除这个自定义栏目</label>
          <label>栏目小标题</label>
          <input name="sectionEyebrow" value="{html_escape(home_section.get('eyebrow', ''))}" placeholder="Now">
          <label>栏目标题</label>
          <input name="sectionTitle" value="{html_escape(home_section.get('title', ''))}" placeholder="正在整理的方向">
          <label>栏目内容</label>
          <textarea name="sectionBody">{html_escape(home_section.get('body', ''))}</textarea>
          <label>栏目链接文字</label>
          <input name="sectionLinkLabel" value="{html_escape(home_section.get('linkLabel', ''))}" placeholder="了解更多">
          <label>栏目链接</label>
          <input name="sectionLinkHref" value="{html_escape(home_section.get('linkHref', ''))}" placeholder="/about/">
          <span class="hint">背景图会保存到 site/public/uploads/home/，支持 jpg、jpeg、png、webp、avif、gif、svg；更推荐 webp/jpg/png。</span>
          <div class="actions"><button type="submit">保存首页设置</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>给文章插入图片</h2>
        <form method="post" action="/action/insert_post_image" enctype="multipart/form-data">
          <label>选择文章</label>
          <select name="file" {'disabled' if not posts else ''}>{image_post_options or '<option>暂无文章</option>'}</select>
          <label>图片说明（会作为 alt 文本）</label>
          <input name="alt" placeholder="例如：控制面板截图">
          <label>选择图片（jpg、png、webp、avif、gif、svg）</label>
          <input name="image" required type="file" accept=".jpg,.jpeg,.png,.webp,.avif,.gif">
          <span class="hint">保存后会自动把 Markdown 图片语法追加到文章末尾，你也可以打开文章编辑区，把那一行移动到正文中想放的位置。</span>
          <div class="actions"><button type="submit" {'disabled' if not posts else ''}>上传并插入</button></div>
        </form>
      </div>
      <div class="section-title" id="data-section">
        <h2>友链、列表和状态</h2>
        <p>友链维护、Git 状态、文章显示/分享入口放在最后，方便检查。</p>
      </div>
      <div class="panel">
        <h2>添加友链</h2>
        <form method="post" action="/action/add_friend" enctype="multipart/form-data">
          <label>名称</label>
          <input name="name" required>
          <label>链接</label>
          <input name="url" required placeholder="https://">
          <label>简介</label>
          <input name="description">
          <label>头像</label>
          <input name="avatar" placeholder="/favicon.svg 或 https://...">
          <label>上传头像（推荐本地保存，避免外链失效）</label>
          <input name="avatarFile" type="file" accept=".jpg,.jpeg,.png,.webp,.avif,.gif">
          <span class="hint">上传头像会保存到 site/public/uploads/avatars/，友链页会自动使用 /favicon.svg 作为加载失败兜底。</span>
          <div class="actions"><button type="submit">添加友链</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>Git 状态</h2>
        <pre>{html_escape(git_status)}</pre>
      </div>
      <div class="panel wide">
        <h2>文章列表</h2>
        <p class="muted">“显示”的文章会出现在网站并可以分享；“隐藏”的文章不会出现在公开页面里，别人打开线上链接也看不到。</p>
        <table>
          <thead><tr><th>状态</th><th>标题</th><th>日期</th><th>标签</th><th>文件</th><th>操作</th><th>分享</th></tr></thead>
          <tbody>{post_rows}</tbody>
        </table>
      </div>
      <div class="panel wide">
        <h2>友链列表</h2>
        <table>
          <thead><tr><th>名称</th><th>链接</th><th>简介</th><th>操作</th></tr></thead>
          <tbody>{friend_rows}</tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    document.querySelectorAll('.copy-link').forEach((button) => {{
      button.addEventListener('click', async () => {{
        const url = button.dataset.url || '';
        try {{
          await navigator.clipboard.writeText(url);
          button.textContent = '已复制';
        }} catch (error) {{
          window.prompt('复制这条链接：', url);
        }}
      }});
    }});
  </script>
</body>
</html>"""


class BlogPanelServer(ThreadingHTTPServer):
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class BlogPanelHandler(BaseHTTPRequestHandler):
    def trusted_request(self) -> bool:
        host = self.headers.get("Host", "")
        return is_trusted_host(host, self.server.server_port)

    def do_HEAD(self) -> None:
        if not self.trusted_request():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_html(render_page(), include_body=False)

    def do_GET(self) -> None:
        if not self.trusted_request():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            edit_file = query.get("edit", [""])[-1]
            self.send_html(render_page(edit_file=edit_file))
            return
        if parsed.path == "/post/new":
            title = query.get("title", [""])[-1].strip() or "新文章"
            description = query.get("description", [""])[-1].strip() or "这是一篇新的博客文章。"
            tags = [tag.strip() for tag in re.split(r"[,，]", query.get("tags", [""])[-1]) if tag.strip()]
            pub_date = query.get("pubDate", [""])[-1].strip() or date.today().isoformat()
            draft = query.get("draft", ["on"])[-1] == "on"
            template_rel = query.get("template", [""])[-1]
            requested_suffix = ".mdx" if query.get("format", ["md"])[-1] == "mdx" else ".md"
            content, template_suffix = source_from_template(template_rel, title, description, tags, draft, pub_date)
            suffix = template_suffix if template_rel else requested_suffix
            self.send_html(
                render_editor_page(
                    rel_file="__new_post__",
                    content=content,
                    kind=suffix.lstrip("."),
                    title="新建文章",
                    suffix=suffix,
                    is_new_post=True,
                )
            )
            return
        if parsed.path == "/post/edit":
            rel_file = query.get("file", [""])[-1]
            path = post_path_from_rel(rel_file)
            if not path:
                self.send_html(render_page(CommandResult(1, "没有找到要编辑的文章。")))
                return
            self.send_html(
                render_editor_page(
                    rel_file=relative_to_root(path),
                    content=read_text_file(path),
                    kind=path.suffix.lower().lstrip("."),
                    title=f"编辑文章：{path.name}",
                )
            )
            return
        if parsed.path == "/file/edit":
            rel_file = query.get("file", [""])[-1]
            path = safe_root_file(rel_file)
            if not path:
                self.send_html(render_page(CommandResult(1, "文件路径无效，或这个文件类型不允许在面板里编辑。")))
                return
            site_route = route_for_page_file(path) or ""
            if site_route:
                start_preview()
            self.send_html(
                render_editor_page(
                    rel_file=relative_to_root(path),
                    content=read_text_file(path),
                    kind=path.suffix.lower().lstrip(".") or "text",
                    title=f"编辑文件：{path.name}",
                    site_route=site_route,
                )
            )
            return
        if parsed.path.startswith("/uploads/") or parsed.path in {"/favicon.svg", "/favicon.ico"}:
            public_path = (SITE_DIR / "public" / parsed.path.lstrip("/")).resolve()
            try:
                public_path.relative_to((SITE_DIR / "public").resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not public_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file(public_path)
            return
        if parsed.path.startswith("/preview_asset/"):
            asset_rel = parsed.path.removeprefix("/preview_asset/").replace("\\", "/").lstrip("/")
            asset_path = (ROOT / asset_rel).resolve()
            try:
                asset_path.relative_to(ROOT.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not asset_path.is_file() or asset_path.suffix.lower() not in IMAGE_EXTENSIONS:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file(asset_path)
            return
        else:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

    def do_POST(self) -> None:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin", "")
        if not self.trusted_request() or not is_trusted_origin(origin, host):
            self.send_text("请求来源无效，操作已拒绝。", status=HTTPStatus.FORBIDDEN)
            return

        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_text("请求长度无效。", status=HTTPStatus.BAD_REQUEST)
            return
        if length < 0 or length > MAX_REQUEST_BYTES:
            self.send_text("请求过大，单次提交最多 32 MiB。", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        content_type = self.headers.get("Content-Type", "")
        raw_body = self.rfile.read(length)
        files: dict[str, UploadedFile] = {}
        multi_files: dict[str, list[UploadedFile]] = {}
        if content_type.startswith("multipart/form-data"):
            form, multi_files = parse_multipart_multi(raw_body, content_type)
            files = {key: values[-1] for key, values in multi_files.items() if values}
        else:
            body = raw_body.decode("utf-8", errors="replace")
            form = {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}

        supplied_token = form.pop("_csrf", "")
        if not supplied_token or not secrets.compare_digest(supplied_token, CSRF_TOKEN):
            self.send_text("页面校验已失效，请刷新控制面板后重试。", status=HTTPStatus.FORBIDDEN)
            return

        if parsed.path == "/action/save_source":
            result = save_source_file(form)
            self.send_text(result.output, status=HTTPStatus.OK if result.code == 0 else HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/action/upload_editor_images":
            result = upload_editor_images(multi_files)
            self.send_text(result.output, status=HTTPStatus.OK if result.code == 0 else HTTPStatus.BAD_REQUEST)
            return

        actions = {
            "/action/check_requirements": lambda _: check_requirements(),
            "/action/install_dependencies": lambda _: install_dependencies(),
            "/action/create_post": create_post,
            "/action/publish_post": publish_post,
            "/action/set_post_visibility": set_post_visibility,
            "/action/save_post_template": save_post_as_template,
            "/action/save_post": lambda data: save_post(data, files),
            "/action/insert_post_image": lambda data: insert_post_image(data, files),
            "/action/update_home": lambda data: update_home_settings(data, files),
            "/action/update_navigation": update_navigation,
            "/action/update_footer": update_footer,
            "/action/update_theme": lambda data: update_theme(data, files),
            "/action/add_friend": lambda data: add_friend(data, files),
            "/action/delete_friend": delete_friend,
            "/action/start_preview": lambda _: start_preview(),
            "/action/stop_preview": lambda _: stop_preview(),
            "/action/build": lambda _: build_site(),
            "/action/update_blog": update_blog,
        }
        action = actions.get(parsed.path)
        if not action:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_html(render_page(action(form)))

    def send_html(self, content: str, include_body: bool = True) -> None:
        payload = inject_csrf_fields(content).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_security_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if include_body:
            self.wfile.write(payload)

    def send_text(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_security_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path: Path) -> None:
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_security_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")


def serve_panel(port: int, no_browser: bool = False) -> int:
    url = f"http://{PANEL_HOST}:{port}/"
    try:
        server = BlogPanelServer((PANEL_HOST, port), BlogPanelHandler)
    except OSError as exc:
        if is_panel_ready(port):
            print(f"控制面板已经在运行：{url}")
            if not no_browser:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            return 0
        print(f"无法启动控制面板：端口 {port} 已被占用。", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Blog panel is running: {url}")
    print("Press Ctrl+C to stop.")
    if not no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping panel...")
    finally:
        stop_preview()
        server.server_close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local blog control panel.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument("--port", type=int, default=PANEL_PORT, help="Panel port, default: 8765.")
    args = parser.parse_args()

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    POST_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    FRIENDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    HOME_FILE.parent.mkdir(parents=True, exist_ok=True)
    NAVIGATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOOTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    THEME_FILE.parent.mkdir(parents=True, exist_ok=True)
    (PUBLIC_FONTS_DIR / "custom").mkdir(parents=True, exist_ok=True)
    if not FRIENDS_FILE.exists():
        write_friends([])
    if not HOME_FILE.exists():
        write_home(DEFAULT_HOME)
    if not NAVIGATION_FILE.exists():
        write_navigation(DEFAULT_NAVIGATION)
    if not FOOTER_FILE.exists():
        write_footer(DEFAULT_FOOTER)
    if not THEME_FILE.exists():
        write_theme(DEFAULT_THEME)
    initialize_post_templates()
    return serve_panel(args.port, args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
