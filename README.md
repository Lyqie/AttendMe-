# AttendMe — 云端多模态注意力检测系统

基于云端多模态大模型（DashScope Qwen VL）的实时注意力监测工具。
截图发送至云端 API 进行分析，本地仅运行轻量 UI。

## 效果预览

- **悬浮窗**：毛玻璃圆角窗口，环形进度条显示当前注意力分数（绿/橙/红）
- **历史趋势**：可展开的平滑折线图 + 渐变面积填充，支持 5/15/60 分钟切换
- **统计面板**：今日专注时长、平均分、打断次数、按应用分布
- **白名单/忽略**：可自定义白名单应用，或临时忽略窗口 5 分钟

## 系统要求

- Windows 10/11
- Python 3.10+

## 快速开始

### 1. 获取 DashScope API Key

1. 访问 [阿里云 DashScope](https://dashscope.console.aliyun.com/)
2. 开通模型服务，获取 API Key

### 2. 配置 API Key

在 `config.json` 中填写 `api_key`，或设置环境变量：

```bash
set DASHSCOPE_API_KEY=your-api-key-here
```

### 3. 安装依赖

```bash
cd AttendMe
pip install -r requirements.txt
```

### 4. 运行

```bash
python main.py
```

## 配置说明

编辑 `config.json`：

```json
{
    "model": {
        "provider": "dashscope",                      // API 提供商
        "model_name": "qwen3.5-vl-flash",            // 模型名称
        "api_key": "",                                // API Key（留空则读环境变量 DASHSCOPE_API_KEY）
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "timeout_seconds": 30,
        "max_retries": 2
    },
    "capture": {
        "interval_seconds": 4,          // 截图间隔（建议 4-5 秒，考虑 API 延迟）
        "monitor_index": 0,
        "max_dimension": 1024,          // 截图最大边长
        "image_quality": 75
    },
    "ui": {
        "always_on_top": true,
        "collapsed_size": [190, 260],
        "expanded_size": [520, 600],
        "position": [60, 120],
        "frosted_glass": true
    },
    "whitelist": {
        "process_names": ["code.exe", "pycharm64.exe"],
        "window_titles": []
    },
    "ignore_duration_minutes": 5
}
```

## 支持的其他 API

任何兼容 OpenAI Chat Completions 格式的多模态 API 均可使用，只需修改 `api_base` 和 `model_name`：

| 提供商 | api_base | model_name 示例 |
|--------|----------|-----------------|
| DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3.5-vl-flash`, `qwen-vl-max` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| vLLM (自建) | `http://your-server:8000/v1` | 任意 |

## 项目结构

```
AttendMe/
├── main.py               # 入口，应用编排
├── screen_capture.py     # 屏幕截图（mss）+ 活动窗口信息
├── model_inference.py    # 云端 VL API 调用（OpenAI 兼容格式）+ QThread
├── ui_components.py      # PySide6 UI 组件（悬浮窗、图表、统计）
├── data_manager.py       # SQLite 数据持久化 + JSON 导出
├── config.json           # 用户配置（含 API Key）
├── requirements.txt      # Python 依赖
└── attendme.db           # 运行后自动生成
```

## 常见问题

**Q: 提示"API 未连接"**
A: 确认 `config.json` 中已填写 `api_key`，或已设置环境变量 `DASHSCOPE_API_KEY`。

**Q: API 响应太慢**
A: `qwen3.5-vl-flash` 是轻量模型，通常 1-3 秒返回。如仍慢，可降低 `max_dimension` 减小图片。

**Q: 如何在多显示器上使用？**
A: 修改 `config.json` 中的 `monitor_index`。
