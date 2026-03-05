# FindWords - 古籍词语检索分析系统

一个轻量化的本地古籍词语检索与智能分析工具。上传古籍 PDF 文档，通过全文检索快速定位词语出处，并借助 AI 对检索结果进行深度分析与多轮对话。

## 功能概览

- **全文检索** - 上传古籍 PDF，自动建立索引，支持简繁体关键词搜索
- **CBETA 在线检索** - 可选接入 CBETA 线上佛典数据库，扩展检索范围
- **AI 智能分析** - 基于检索结果，由大模型提取出处、分析上下文、按朝代排序
- **多轮对话** - 针对检索结果进行追问，支持历史会话管理
- **PDF 阅读器** - 内置阅读器，点击搜索结果直接跳转对应页面并高亮关键词
- **朝代与分类筛选** - 为文件标注朝代（先秦～宋元明清）和文献分类（本土文献/汉译佛典/中土佛教文献），检索结果可按此筛选
- **多模型支持** - 兼容 DeepSeek、Qwen、Kimi、MiniMax 等 OpenAI 兼容格式的大模型
- **跨平台桌面应用** - 基于 Electron 封装，支持 macOS、Windows、Linux

## 项目结构

```
FindWords/
├── backend/                  # Python 后端 (FastAPI)
│   ├── app/
│   │   ├── agents/           # LangGraph 智能体 (检索 + 对话)
│   │   ├── api/              # REST API 路由
│   │   ├── core/             # 数据库、WebSocket 管理
│   │   ├── models/           # Pydantic 数据模型
│   │   └── services/         # PDF 处理、CBETA 爬虫
│   ├── hooks/                # PyInstaller 运行时钩子
│   ├── data/                 # 开发模式数据目录
│   ├── requirements.txt
│   ├── run_server.py         # PyInstaller 入口
│   └── findwords-server.spec # PyInstaller 打包配置 (one-dir 模式)
├── frontend/                 # React + Electron 前端
│   ├── electron/
│   │   ├── main.cjs          # Electron 主进程
│   │   └── icons/            # 应用图标 (.png/.icns/.ico)
│   ├── src/                  # React 源码 (Vite + TypeScript + TailwindCSS)
│   ├── electron-builder.yml  # electron-builder 打包配置
│   ├── package.json
│   └── vite.config.ts
├── build.sh                  # macOS/Linux 一键构建脚本
├── build-win.bat             # Windows 一键构建脚本
├── package.json              # 根目录便捷脚本
└── README.md
```

## 环境要求

| 工具 | 版本要求 | 用途 |
|------|---------|------|
| **Python** | ≥ 3.10 | 后端运行 |
| **Node.js** | ≥ 18 | 前端构建 & Electron |
| **npm** | ≥ 9 | 包管理 |
| **PyInstaller** | ≥ 6.0 | 打包后端为可执行文件 |

## 快速开始

### 1. 安装依赖

```bash
# 后端依赖
cd backend
pip install -r requirements.txt

# 前端依赖
cd frontend
npm install
```

### 2. 开发模式

需要开启两个终端：

**终端 1 — 启动后端：**

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

**终端 2 — 启动前端 + Electron（一键）：**

```bash
cd frontend
npm run dev:electron
```

这会同时启动 Vite 开发服务器（端口 5173）和 Electron 窗口。Vite 就绪后 Electron 自动打开。

> 如果只需网页版，运行 `npm run dev` 后访问 http://localhost:5173

### 3. 配置大模型

启动后在应用内「设置」页面配置：
- 选择模型提供商（DeepSeek / Qwen / Kimi / MiniMax）
- 填写 API Key
- 选择模型名称

---

## 打包桌面应用

### 前置准备

#### 应用图标

图标文件位于 `frontend/electron/icons/`：

| 文件 | 平台 | 格式要求 |
|------|------|---------|
| `icon.png` | 源文件 | 1024×1024 PNG |
| `icon.icns` | macOS | 由 PNG 转换生成 |
| `icon.ico` | Windows | 含 16~256px 多尺寸 |

**从 PNG 生成图标（macOS 上执行）：**

```bash
cd frontend/electron/icons

# 生成 macOS .icns
mkdir -p icon.iconset
for size in 16 32 64 128 256 512; do
  sips -z $size $size icon.png --out icon.iconset/icon_${size}x${size}.png
  double=$((size * 2))
  sips -z $double $double icon.png --out icon.iconset/icon_${size}x${size}@2x.png
done
cp icon.png icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset -o icon.icns
rm -rf icon.iconset

# 生成 Windows .ico（需要 Python + Pillow）
python3 -c "
from PIL import Image
img = Image.open('icon.png')
sizes = [(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)]
img.save('icon.ico', format='ICO', sizes=sizes)
"
```

### 打包步骤详解

打包分为三个阶段：**构建前端** → **打包后端** → **生成安装包**。

#### 第一步：构建前端

```bash
cd frontend
npm run build
```

输出到 `frontend/dist/`，包含编译后的 HTML/CSS/JS 静态文件。

#### 第二步：打包后端可执行文件

> ⚠️ **PyInstaller 不支持跨平台编译**，必须在目标平台上执行此步骤。
> 例如：打 Windows 包必须在 Windows 机器上运行。

```bash
cd backend
pip install pyinstaller
pyinstaller findwords-server.spec --clean -y
```

输出到 `backend/dist/findwords-server/` **目录**（one-dir 模式），包含可执行文件 `findwords-server` 和 `_internal/` 依赖目录。

> **为什么使用 one-dir 模式？** 相比 one-file 模式（将所有文件打包成单个可执行文件），one-dir 模式避免了每次启动时解压 ~127MB 临时文件的开销，启动时间从 **~45 秒降至 ~1 秒**。

#### 第三步：生成安装包

```bash
cd frontend

# 当前平台
npm run dist

# 或指定平台
npm run dist:mac      # macOS → .dmg + .zip
npm run dist:win      # Windows → NSIS 安装包 + Portable
npm run dist:linux    # Linux → .AppImage + .deb
```

输出到 `frontend/release/` 目录。

#### 一键构建（当前平台）

**macOS / Linux：**

```bash
# 方式一：使用根目录构建脚本（自动创建 venv、安装依赖）
./build.sh

# 方式二：使用 npm 脚本（需已安装依赖）
cd frontend
npm run build:all
```

两者等价于依次执行：安装依赖 → 构建前端 → PyInstaller 打包后端 → electron-builder 生成安装包。

**Windows：**

```cmd
build-win.bat
```

该脚本自动完成全部四个步骤：安装依赖 → 构建前端 → 打包后端 → 生成 NSIS 安装包。

### electron-builder 配置说明

配置文件：`frontend/electron-builder.yml`

```yaml
appId: com.findwords.app
productName: FindWords

files:              # Electron 主进程文件
  - electron/**/*
  - package.json

extraResources:     # 附加资源（安装后释放到 resources/ 目录）
  - from: ../backend/dist/findwords-server/   # 后端 one-dir 整个目录
    to: backend
  - from: dist/                               # 前端静态文件
    to: frontend-dist
```

> `extraResources` 中 `from` 指向 PyInstaller one-dir 输出目录 `backend/dist/findwords-server/`，安装后释放到应用 `resources/backend/` 下，Electron 主进程在此路径启动后端进程。

**各平台输出格式：**

| 平台 | 输出格式 | 输出目录 |
|------|---------|----------|
| macOS | `.dmg` + `.zip` | `frontend/release/` |
| Windows | NSIS 安装包 + Portable | `frontend/release/` |
| Linux | `.AppImage` + `.deb` | `frontend/release/` |

**NSIS 安装包选项（Windows）：**
- 支持自定义安装目录
- 中英双语安装界面

---

## 数据存储位置

安装后应用数据存储在用户目录下（由 Electron `app.getPath('userData')` 决定）：

| 平台 | 路径 |
|------|------|
| **Windows** | `%APPDATA%\FindWords\data\` |
| **macOS** | `~/Library/Application Support/FindWords/data/` |
| **Linux** | `~/.config/FindWords/data/` |

该目录包含：

| 文件/目录 | 说明 |
|----------|------|
| `findwords.db` | SQLite 数据库（文件索引、会话、搜索结果） |
| `config.json` | 应用配置（模型设置、API Key 等） |
| `uploads/` | 上传的 PDF 文件 |

> 开发模式下，数据存放在 `backend/data/` 目录中。

---

## 可用脚本

在 `frontend/` 目录下执行：

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动 Vite 开发服务器（仅网页） |
| `npm run dev:electron` | 同时启动 Vite + Electron（开发用） |
| `npm run electron` | 仅启动 Electron（需先启动 Vite） |
| `npm run build` | 构建前端生产版本 |
| `npm run build:all` | 一键构建（前端 + 后端 + 安装包） |
| `npm run dist` | 打包当前平台安装包 |
| `npm run dist:mac` | 打包 macOS 安装包 |
| `npm run dist:win` | 打包 Windows 安装包 |
| `npm run dist:linux` | 打包 Linux 安装包 |

## 技术栈

- **后端**: FastAPI, LangGraph, OpenAI SDK, SQLite FTS5, OpenCC, PyMuPDF
- **前端**: React 18, TypeScript, Vite, TailwindCSS, react-markdown
- **桌面**: Electron 33, electron-builder
- **通信**: WebSocket (实时流式输出), REST API

## 许可证

[MIT License](LICENSE) - Copyright (c) 2026 Chen Shengfeng
