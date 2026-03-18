# ai-shortdrama-agent（短剧长篇生成工作流）

这是一个面向“短剧/微短剧”的长篇生成工作流，按固定阶段产出结构化 JSON，并在多集之间通过 `series_memory` 保持连续性。

## 你会得到什么

1. `series-setup`：生成长篇系列的基础材料
2. `episode-batch`：按集生成 `plot / script / storyboard`，并更新 `series_memory`

所有生成结果都会落在仓库内的：

`ai_manga_factory/runs/`

并且每个剧名目录下包含：

- `series_setup.json`
- `series_outline.json`
- `character_bible.json`
- `episode_pitch.json`
- `series_memory.json`
- `episode_batch.json`

以及每集子目录：

- `plot.json`
- `script.json`
- `storyboard.json`
- `creative_scorecard.json`
- `package.json`

## 环境准备

### 1）Python

建议使用 Python 3.10+。

### 2）依赖

项目代码使用了以下包（按需安装即可）：

- `google-adk`（ADK Runner/Agent/Session）
- `google-genai`（模型调用）
- `python-dotenv`（加载 `.env`）

示例（可按你实际环境调整版本）：

```bash
pip install google-adk google-genai python-dotenv
```

## 关键源码依赖（必须存在）

`run_series.py` 会依赖仓库中的：

- `ai_manga_factory/agent.py`（提供 `root_agent`、语言策略等）
- `ai_manga_factory/__init__.py`（确保包导入正常）

如果你采用“只推指定文件”的策略到远端，请确保部署环境里这些文件也能被访问到（否则命令会导入失败）。

### 3）API Key（必须）

在 `ai_manga_factory/.env` 放置你的密钥，至少包含：

- `GOOGLE_API_KEY`（Gemini/VertexAI 使用）
- `GOOGLE_GENAI_USE_VERTEXAI`（可选，按你环境配置）

注意：密钥与生产数据（如 `runs/`）不要提交到 Git。

## 使用方法（CLI）

入口脚本：

- `python -m ai_manga_factory.run_series`

### 1）series-setup（先生成系列大纲/角色/初始 memory）

示例：

```powershell
cd "d:\AI_Agent\ai-shortdrama-agent-adk"

python -m ai_manga_factory.run_series --mode series-setup `
  --theme "系统+求生+规则验证" `
  --audience-view "青年男性，节奏快、爽点密集" `
  --quality-mode fast
```

执行完成后，去 `ai_manga_factory/runs/<剧名>/` 找到上述 JSON 文件。

### 2）episode-batch（逐集生成并持续更新 series_memory）

示例（生成第 1-3 集）：

```powershell
python -m ai_manga_factory.run_series --mode episode-batch `
  --series-outline "d:\AI_Agent\ai-shortdrama-agent-adk\ai_manga_factory\runs\<剧名>\series_outline.json" `
  --character-bible "d:\AI_Agent\ai-shortdrama-agent-adk\ai_manga_factory\runs\<剧名>\character_bible.json" `
  --series-memory "d:\AI_Agent\ai-shortdrama-agent-adk\ai_manga_factory\runs\<剧名>\series_memory.json" `
  --episodes "1-3"
```

运行过程中会把每集产物写入：

- `ai_manga_factory/runs/<剧名>/episodes/<剧名>_第XXX集/`

并把更新后的 `series_memory.json` 回写到：

- `ai_manga_factory/runs/<剧名>/series_memory.json`

## 数据结构约定（简表）

### `series_memory.json`

结构：

```json
{
  "episodes": [
    { "episode_id": 3, "summary": "...", "open_threads": ["..."] }
  ],
  "characters": [
    { "name": "李岩", "first_episode": 3, "last_appeared_episode": 3, "status": "alive", "appearance_hint": "..." }
  ]
}
```

说明：

- `characters` 只包含“有名字的角色”，`群众/观众` 不入该表。
- `episodes.open_threads` 用于跨集回扣与悬念延续。

## 安全与仓库约束

建议你始终遵守：

- 不提交 `ai_manga_factory/.env`
- 不提交 `ai_manga_factory/runs/`（生产输出）
- 不提交 `.venv/`

如果你要工业化部署（CI/CD 或多人协作），推荐补一个 `.gitignore` 来强制忽略上述目录/文件。
