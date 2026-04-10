# Anthropic OAuth / Claude Code 客户端身份（clawcode）

clawcode 实现位于 [`anthropic_resolve.py`](anthropic_resolve.py)，由 [`AnthropicProvider`](../providers/anthropic.py) 使用。  
**范围**：路径 A（进程内 API）；与路径 B（`claude` CLI 子进程）无关，见 [`CLAW_SUPPORT_MAP.md`](CLAW_SUPPORT_MAP.md)。

## 常量与列表（应保持同步）

| 项目 | 参考（Claude Code 兼容） | clawcode `anthropic_resolve` |
|------|---------------------------|-------------------------------|
| 通用 beta（所有鉴权类型） | `_COMMON_BETAS` | `_COMMON_BETAS`（同名列表） |
| OAuth 专用 beta | `_OAUTH_ONLY_BETAS` | `_OAUTH_ONLY_BETAS`（同名列表） |
| CLI 版本兜底（UA） | `_CLAUDE_CODE_VERSION_FALLBACK = "2.1.74"` | `_CLAUDE_CODE_VERSION_FALLBACK = "2.1.74"` |
| OAuth refresh `client_id` | （与控制台 OAuth 一致） | `_OAUTH_CLIENT_ID`（与 Claude Code 刷新流一致） |
| Token 端点 | （见 Anthropic 控制台） | `_TOKEN_ENDPOINT = https://console.anthropic.com/v1/oauth/token` |

### `_COMMON_BETAS`（当前）

1. `interleaved-thinking-2025-05-14`
2. `fine-grained-tool-streaming-2025-05-14`

### `_OAUTH_ONLY_BETAS`（当前）

1. `claude-code-20250219`
2. `oauth-2025-04-20`

## OAuth / Bearer 分支请求头（与 Claude Code 一致）

当 token **不是** `sk-ant-api…` 时（`is_oauth_token` / `_is_oauth_token` 为真）：

| 头 | 值 |
|----|-----|
| `anthropic-beta` | `",".join(_COMMON_BETAS + _OAUTH_ONLY_BETAS)` |
| `user-agent` | `claude-cli/{version} (external, cli)`，`version` 来自 `claude` / `claude-code` 的 `--version`，失败则用兜底版本 |
| `x-app` | `cli` |

Console API Key（`sk-ant-api…`）分支：使用 `api_key` + 仅 `_COMMON_BETAS`（无 OAuth 专用 beta、无 `x-app`）。

## 刷新令牌请求（clawcode）

[`refresh_claude_oauth_token`](anthropic_resolve.py) 的 HTTP `User-Agent` 使用同一 `claude-cli/{detect_claude_code_version()} (external, cli)` 形式，与进程内 Async 客户端一致。

## 回归测试

[`tests/test_anthropic_resolve.py`](../../../tests/test_anthropic_resolve.py) 中含 `test_anthropic_compat_*`，在更新 `_COMMON_BETAS` / `_OAUTH_ONLY_BETAS` / 兜底版本时**应同步修改**上述表与本文件，并跑测试。

## clawcode 未实现的可选路径

- 部分可选第三方 OAuth 路径：clawcode **不读**；见 [`CLAW_SUPPORT_MAP.md`](CLAW_SUPPORT_MAP.md) 鉴权表。
