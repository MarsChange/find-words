# FindWords - 古籍词语检索分析系统

一个轻量化的本地古籍词语检索与智能分析工具。上传古籍 PDF 文档，通过全文检索快速定位词语出处，并借助 AI 对检索结果进行深度分析与多轮对话。

## 功能概览

- **全文检索** - 上传古籍 PDF，自动建立索引，支持简繁体关键词搜索
- **CBETA 在线检索** - 可选接入 CBETA 线上佛典数据库，扩展检索范围
- **AI 智能分析** - 基于检索结果，由大模型提取出处、分析上下文、按朝代排序
- **多轮对话** - 针对检索结果进行追问，支持历史会话管理
- **PDF 阅读器** - 内置阅读器，点击搜索结果直接跳转对应页面并高亮关键词
- **多模型支持** - 兼容 DeepSeek、Qwen、Kimi、MiniMax 等 OpenAI 兼容格式的大模型

## 快速开始

### 后端

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

启动后访问 http://localhost:5173，在设置页面配置大模型 API Key 即可使用。

## 许可证

[MIT License](LICENSE) - Copyright (c) 2026 Chen Shengfeng
