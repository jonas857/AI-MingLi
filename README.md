# AI MingLi

AI MingLi is an AI-assisted Chinese metaphysics product for self-understanding. It combines local BaZi chart calculation, Ziwei chart generation, prompt engineering, multi-model interpretation, and a layered long-term memory system.

The product goal is not only to produce a one-off fortune reading, but to help users build a clearer personal narrative through structured chart facts, repeated analysis, and gradually refined memory.

## Core Product Loop

The main user journey is:

1. User enters personal birth information.
2. The system calculates BaZi chart facts locally when possible.
3. The user selects one or more analysis dimensions.
4. Prompt templates combine chart facts, user background, dimension instructions, and shared memory.
5. DeepSeek or Gemini generates the interpretation.
6. The full analysis is returned immediately.
7. A separate memory organizer later extracts durable profile, insight, and memory items.
8. Future prompts dynamically inject the latest memory context.

```mermaid
flowchart TD
  A["主请求：用户点分析"] --> B["主模型 DeepSeek/Gemini 生成命理解读"]
  B --> C["立即返回给用户"]
  B --> D["同步保存完整分析文本"]
  D --> E["写入 raw event 队列"]
  E --> F["异步整理器唤醒"]
  F --> G["记忆整理模型 deepseek-v4-flash / MEMORY_ORGANIZER_MODEL"]
  G --> H["提炼 profile / insight / memory_items"]
  H --> I["保存到本地 JSON 与可选向量库"]
  I --> J["下一次构建提示词时动态注入"]
```

## BaZi Calculation Flow

BaZi calculation is designed as a local-first pipeline. The backend normalizes user input and prefers the local Node bridge. If local calculation fails and the provider mode allows fallback, it calls the MCP-based provider.

```mermaid
flowchart TD
  A["用户输入姓名、性别、阳历/农历、出生时间"] --> B["前端 birth_input.html 格式化时间"]
  B --> C["POST /api/bazi/get"]
  C --> D["app_simplified._build_bazi_calculation_args 标准化参数"]
  D --> E{"BAZI_CALC_PROVIDER"}
  E -->|"auto/local"| F["local_bazi_calculator.py"]
  F --> G["启动 bazi_local_node.mjs"]
  G --> H{"输入类型"}
  H -->|"solarDatetime"| I["bazi-mcp getBaziDetail"]
  H -->|"lunarDatetime"| J["tyme4ts LunarHour + bazi-mcp buildBazi"]
  I --> K["返回四柱、五行、十神、农历、节气、raw_data"]
  J --> K
  E -->|"mcp 或 local 失败回退"| L["bazi_client.py 调用 bazi-mcp / Smithery MCP"]
  L --> K
  K --> M["保存 local_data/bazi_data/<user_id>_bazi.json"]
  M --> N["memory_manager.update_chart_facts_from_bazi_payload"]
  N --> O["生成 chart_facts：命盘硬事实、摘要、chart_signature"]
  O --> P["后续提示词注入和 PDF 导出复用"]
```

Key files:

- `birth_input.html`: collects and formats birth information.
- `app_simplified.py`: exposes `POST /api/bazi/get`, validates input, chooses provider, saves user chart data.
- `local_bazi_calculator.py`: Python wrapper around the local Node process.
- `bazi_local_node.mjs`: local Node bridge using `bazi-mcp` and `tyme4ts`.
- `bazi_client.py`: MCP fallback client.
- `memory_manager.py`: extracts stable `chart_facts` from BaZi payloads.

## Ziwei Calculation Flow

Ziwei is implemented as a separate MCP-backed chart service. It is gated by `ENABLE_MCP_ZIWEI`, then used by the Ziwei page and chat workflow.

```mermaid
flowchart TD
  A["用户在紫微页面提交出生信息"] --> B["POST /api/ziwei/chart"]
  B --> C{"ENABLE_MCP_ZIWEI"}
  C -->|"false"| D["返回 ziwei mcp disabled"]
  C -->|"true"| E["app_simplified.api_ziwei_chart 清洗 birth_date / birth_time / gender / location"]
  E --> F["ZiweiClient.generate_chart"]
  F --> G["解析/补全 location，经纬度和时区"]
  G --> H["调用 ziwei-mcp generate_chart"]
  H --> I["返回紫微命盘 chart / chart_id"]
  I --> J{"存在 chart_id"}
  J -->|"yes"| K["ZiweiClient.interpret_chart 调用 interpret_chart"]
  J -->|"no"| L["仅返回 chart"]
  K --> M["返回 chart + interpret"]
  L --> M
  M --> N["前端展示紫微盘，并进入紫微问答"]
  N --> O["/api/ziwei/chat/send 构建紫微问答提示词"]
  O --> P["注入 shared_memory_context"]
  P --> Q["DeepSeek 生成回复"]
  Q --> R["写入 ziwei_chat 历史与 raw event"]
  R --> S["异步整理器沉淀为跨领域记忆"]
```

Key files:

- `ziwei_client.py`: wraps `ziwei-mcp` tool calls, including `generate_chart` and `interpret_chart`.
- `app_simplified.py`: exposes `POST /api/ziwei/chart` and Ziwei chat APIs.
- `analysis-detail.html`: contains Ziwei frontend interactions.
- `memory_manager.py`: Ziwei chat events can be organized into shared memory with domain awareness.

## Prompt and Interpretation Flow

Prompt construction is centralized in `prompt_templates.py`.

```mermaid
flowchart TD
  A["选择分析版本：classic / wisdom / master"] --> B["选择分析维度"]
  B --> C["读取 bazi_info + user_background"]
  C --> D["memory_manager.build_shared_memory_context"]
  D --> E["PromptBuilder.build_analysis_prompt"]
  E --> F["基础人设 + 八字信息 + 用户背景 + 维度要求 + 共享记忆"]
  F --> G["ai_analyzer 调用 DeepSeek / Gemini"]
  G --> H["返回专业版、智慧版或大师版解读"]
```

Supported BaZi dimensions include:

- 日元核心分析
- 天干十神分析
- 地支藏干分析
- 五行生克分析
- 用神忌神分析
- 事业运势分析
- 感情婚姻分析
- 健康状况分析
- 大运流年分析
- 综合建议

## Memory System

The memory system is a layered local-first design. It avoids putting all history into the prompt and instead injects a bounded, filtered context.

Main memory layers:

- `chart_facts`: stable chart facts extracted from BaZi payloads.
- `profile`: user background, preferences, tags, and feedback.
- `insights`: durable conclusions by analysis dimension and version.
- `memory_items`: manageable memory records such as domain insights, support profile items, and episodes.
- `events`: raw event queue consumed by the async organizer.
- optional vector memory: semantic supplement when `ENABLE_VECTOR_MEMORY=true`.

The async organizer is enabled by `ENABLE_ASYNC_ORGANIZER=true`. The main request writes a raw event and returns to the user first. The organizer later uses `MEMORY_ORGANIZER_MODEL` to produce structured memory patches. This creates an eventually consistent memory loop: the current response is fast, and the next response can benefit from newly organized memory.

## Data Safety Boundary

The repository intentionally excludes runtime secrets and user data:

- `.env`
- `local_data/`
- `user_data/`
- `manual_exports/`
- logs
- generated PDFs
- virtual environments
- `node_modules/`

Use `env.template` as the environment variable reference and keep real API keys outside Git.

## Run Locally

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
npm install
copy env.template .env
.\.venv\Scripts\python.exe app_simplified.py
```

Before running AI features, configure the required provider keys in `.env`.

