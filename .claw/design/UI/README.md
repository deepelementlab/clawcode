# `.claw/design/UI/` — Brand UI references

**简介（中文）**  
本目录收录多组 **公开产品/品牌的 UI 美学与组件气质** 参考，用于对齐 TUI/前端/Agent 生成界面时的视觉语言。每个品牌子目录通常包含：结构化 **`DESIGN.md`**（设计令牌与规范）、**`preview.html` / `preview-dark.html`**（本地可打开预览）、以及 **`README.md`**（说明与截图）。下表汇总 **54** 个品牌案例及对应 **源码文件链接**（相对路径，在 GitHub 仓库中可直接点击跳转）。内容均为 **非官方** 从公开站点提炼的参考，可与 VENUS 美学引擎、Stitch 等工作流结合使用。

---

This folder holds **curated, product-style UI references** for ClawCode: each first-level subdirectory is named after a **company, product, or public design language** (for example `stripe`, `linear.app`, `vercel`). Inside every listed brand you will find:

- **`DESIGN.md`** — Markdown design tokens and rules (typography, color, spacing, components, guardrails) suitable for **AI coding agents** and humans.
- **`preview.html` / `preview-dark.html`** — Static token galleries / sample pages you can open locally to sanity-check the spec.
- **`README.md`** — Short notes for that brand, plus optional screenshots.

These are **documentation and inspiration**, not runtime dependencies. Extracts are **unofficial** and may not match vendor systems pixel-perfectly; use them as a **starting point** for VENUS / Stitch-style “design-as-code” workflows.

---

## Brand catalog & code entrypoints

Below, **relative links** work from this file in the repository (GitHub / GitLab / local). Replace `main` with your default branch name in **absolute** URLs if you mirror this tree elsewhere.

| Brand | Role | `DESIGN.md` | `preview.html` | `preview-dark.html` | `README.md` |
|-------|------|----------------------------|----------------------------------|--------------------------------------------|-------------------------|
| [airbnb](./airbnb/) | Travel / marketplace UI | [→](./airbnb/DESIGN.md) | [→](./airbnb/preview.html) | [→](./airbnb/preview-dark.html) | [→](./airbnb/README.md) |
| [airtable](./airtable/) | Database / no-code UI | [→](./airtable/DESIGN.md) | [→](./airtable/preview.html) | [→](./airtable/preview-dark.html) | [→](./airtable/README.md) |
| [apple](./apple/) | Apple marketing / product tone | [→](./apple/DESIGN.md) | [→](./apple/preview.html) | [→](./apple/preview-dark.html) | [→](./apple/README.md) |
| [bmw](./bmw/) | Automotive / premium brand | [→](./bmw/DESIGN.md) | [→](./bmw/preview.html) | [→](./bmw/preview-dark.html) | [→](./bmw/README.md) |
| [cal](./cal/) | Cal.com scheduling | [→](./cal/DESIGN.md) | [→](./cal/preview.html) | [→](./cal/preview-dark.html) | [→](./cal/README.md) |
| [claude](./claude/) | Anthropic Claude product UI | [→](./claude/DESIGN.md) | [→](./claude/preview.html) | [→](./claude/preview-dark.html) | [→](./claude/README.md) |
| [clay](./clay/) | Clay / GTM tooling | [→](./clay/DESIGN.md) | [→](./clay/preview.html) | [→](./clay/preview-dark.html) | [→](./clay/README.md) |
| [clickhouse](./clickhouse/) | ClickHouse data / devtools | [→](./clickhouse/DESIGN.md) | [→](./clickhouse/preview.html) | [→](./clickhouse/preview-dark.html) | [→](./clickhouse/README.md) |
| [cohere](./cohere/) | Cohere AI platform | [→](./cohere/DESIGN.md) | [→](./cohere/preview.html) | [→](./cohere/preview-dark.html) | [→](./cohere/README.md) |
| [coinbase](./coinbase/) | Crypto / fintech | [→](./coinbase/DESIGN.md) | [→](./coinbase/preview.html) | [→](./coinbase/preview-dark.html) | [→](./coinbase/README.md) |
| [composio](./composio/) | Composio integrations | [→](./composio/DESIGN.md) | [→](./composio/preview.html) | [→](./composio/preview-dark.html) | [→](./composio/README.md) |
| [cursor](./cursor/) | Cursor editor / product | [→](./cursor/DESIGN.md) | [→](./cursor/preview.html) | [→](./cursor/preview-dark.html) | [→](./cursor/README.md) |
| [elevenlabs](./elevenlabs/) | Voice / audio AI | [→](./elevenlabs/DESIGN.md) | [→](./elevenlabs/preview.html) | [→](./elevenlabs/preview-dark.html) | [→](./elevenlabs/README.md) |
| [expo](./expo/) | Expo / React Native | [→](./expo/DESIGN.md) | [→](./expo/preview.html) | [→](./expo/preview-dark.html) | [→](./expo/README.md) |
| [figma](./figma/) | Figma product UI | [→](./figma/DESIGN.md) | [→](./figma/preview.html) | [→](./figma/preview-dark.html) | [→](./figma/README.md) |
| [framer](./framer/) | Framer site builder | [→](./framer/DESIGN.md) | [→](./framer/preview.html) | [→](./framer/preview-dark.html) | [→](./framer/README.md) |
| [hashicorp](./hashicorp/) | HashiCorp devtools | [→](./hashicorp/DESIGN.md) | [→](./hashicorp/preview.html) | [→](./hashicorp/preview-dark.html) | [→](./hashicorp/README.md) |
| [ibm](./ibm/) | IBM enterprise / design language | [→](./ibm/DESIGN.md) | [→](./ibm/preview.html) | [→](./ibm/preview-dark.html) | [→](./ibm/README.md) |
| [intercom](./intercom/) | Intercom support / CRM | [→](./intercom/DESIGN.md) | [→](./intercom/preview.html) | [→](./intercom/preview-dark.html) | [→](./intercom/README.md) |
| [kraken](./kraken/) | Kraken exchange | [→](./kraken/DESIGN.md) | [→](./kraken/preview.html) | [→](./kraken/preview-dark.html) | [→](./kraken/README.md) |
| [linear.app](./linear.app/) | Linear issue tracking | [→](./linear.app/DESIGN.md) | [→](./linear.app/preview.html) | [→](./linear.app/preview-dark.html) | [→](./linear.app/README.md) |
| [lovable](./lovable/) | Lovable AI builder | [→](./lovable/DESIGN.md) | [→](./lovable/preview.html) | [→](./lovable/preview-dark.html) | [→](./lovable/README.md) |
| [minimax](./minimax/) | MiniMax AI | [→](./minimax/DESIGN.md) | [→](./minimax/preview.html) | [→](./minimax/preview-dark.html) | [→](./minimax/README.md) |
| [mintlify](./mintlify/) | Mintlify docs | [→](./mintlify/DESIGN.md) | [→](./mintlify/preview.html) | [→](./mintlify/preview-dark.html) | [→](./mintlify/README.md) |
| [miro](./miro/) | Miro whiteboard | [→](./miro/DESIGN.md) | [→](./miro/preview.html) | [→](./miro/preview-dark.html) | [→](./miro/README.md) |
| [mistral.ai](./mistral.ai/) | Mistral AI | [→](./mistral.ai/DESIGN.md) | [→](./mistral.ai/preview.html) | [→](./mistral.ai/preview-dark.html) | [→](./mistral.ai/README.md) |
| [mongodb](./mongodb/) | MongoDB product / docs | [→](./mongodb/DESIGN.md) | [→](./mongodb/preview.html) | [→](./mongodb/preview-dark.html) | [→](./mongodb/README.md) |
| [notion](./notion/) | Notion workspace | [→](./notion/DESIGN.md) | [→](./notion/preview.html) | [→](./notion/preview-dark.html) | [→](./notion/README.md) |
| [nvidia](./nvidia/) | NVIDIA marketing / dev | [→](./nvidia/DESIGN.md) | [→](./nvidia/preview.html) | [→](./nvidia/preview-dark.html) | [→](./nvidia/README.md) |
| [ollama](./ollama/) | Ollama local LLM | [→](./ollama/DESIGN.md) | [→](./ollama/preview.html) | [→](./ollama/preview-dark.html) | [→](./ollama/README.md) |
| [opencode.ai](./opencode.ai/) | OpenCode product | [→](./opencode.ai/DESIGN.md) | [→](./opencode.ai/preview.html) | [→](./opencode.ai/preview-dark.html) | [→](./opencode.ai/README.md) |
| [pinterest](./pinterest/) | Pinterest consumer | [→](./pinterest/DESIGN.md) | [→](./pinterest/preview.html) | [→](./pinterest/preview-dark.html) | [→](./pinterest/README.md) |
| [posthog](./posthog/) | PostHog analytics | [→](./posthog/DESIGN.md) | [→](./posthog/preview.html) | [→](./posthog/preview-dark.html) | [→](./posthog/README.md) |
| [raycast](./raycast/) | Raycast launcher | [→](./raycast/DESIGN.md) | [→](./raycast/preview.html) | [→](./raycast/preview-dark.html) | [→](./raycast/README.md) |
| [replicate](./replicate/) | Replicate ML API | [→](./replicate/DESIGN.md) | [→](./replicate/preview.html) | [→](./replicate/preview-dark.html) | [→](./replicate/README.md) |
| [resend](./resend/) | Resend email API | [→](./resend/DESIGN.md) | [→](./resend/preview.html) | [→](./resend/preview-dark.html) | [→](./resend/README.md) |
| [revolut](./revolut/) | Revolut fintech | [→](./revolut/DESIGN.md) | [→](./revolut/preview.html) | [→](./revolut/preview-dark.html) | [→](./revolut/README.md) |
| [runwayml](./runwayml/) | Runway video AI | [→](./runwayml/DESIGN.md) | [→](./runwayml/preview.html) | [→](./runwayml/preview-dark.html) | [→](./runwayml/README.md) |
| [sanity](./sanity/) | Sanity CMS | [→](./sanity/DESIGN.md) | [→](./sanity/preview.html) | [→](./sanity/preview-dark.html) | [→](./sanity/README.md) |
| [sentry](./sentry/) | Sentry observability | [→](./sentry/DESIGN.md) | [→](./sentry/preview.html) | [→](./sentry/preview-dark.html) | [→](./sentry/README.md) |
| [spacex](./spacex/) | SpaceX aerospace | [→](./spacex/DESIGN.md) | [→](./spacex/preview.html) | [→](./spacex/preview-dark.html) | [→](./spacex/README.md) |
| [spotify](./spotify/) | Spotify consumer | [→](./spotify/DESIGN.md) | [→](./spotify/preview.html) | [→](./spotify/preview-dark.html) | [→](./spotify/README.md) |
| [stripe](./stripe/) | Stripe payments | [→](./stripe/DESIGN.md) | [→](./stripe/preview.html) | [→](./stripe/preview-dark.html) | [→](./stripe/README.md) |
| [supabase](./supabase/) | Supabase BaaS | [→](./supabase/DESIGN.md) | [→](./supabase/preview.html) | [→](./supabase/preview-dark.html) | [→](./supabase/README.md) |
| [superhuman](./superhuman/) | Superhuman email | [→](./superhuman/DESIGN.md) | [→](./superhuman/preview.html) | [→](./superhuman/preview-dark.html) | [→](./superhuman/README.md) |
| [together.ai](./together.ai/) | Together AI | [→](./together.ai/DESIGN.md) | [→](./together.ai/preview.html) | [→](./together.ai/preview-dark.html) | [→](./together.ai/README.md) |
| [uber](./uber/) | Uber mobility | [→](./uber/DESIGN.md) | [→](./uber/preview.html) | [→](./uber/preview-dark.html) | [→](./uber/README.md) |
| [vercel](./vercel/) | Vercel platform | [→](./vercel/DESIGN.md) | [→](./vercel/preview.html) | [→](./vercel/preview-dark.html) | [→](./vercel/README.md) |
| [voltagent](./voltagent/) | VoltAgent | [→](./voltagent/DESIGN.md) | [→](./voltagent/preview.html) | [→](./voltagent/preview-dark.html) | [→](./voltagent/README.md) |
| [warp](./warp/) | Warp terminal | [→](./warp/DESIGN.md) | [→](./warp/preview.html) | [→](./warp/preview-dark.html) | [→](./warp/README.md) |
| [webflow](./webflow/) | Webflow builder | [→](./webflow/DESIGN.md) | [→](./webflow/preview.html) | [→](./webflow/preview-dark.html) | [→](./webflow/README.md) |
| [wise](./wise/) | Wise fintech | [→](./wise/DESIGN.md) | [→](./wise/preview.html) | [→](./wise/preview-dark.html) | [→](./wise/README.md) |
| [x.ai](./x.ai/) | xAI Grok | [→](./x.ai/DESIGN.md) | [→](./x.ai/preview.html) | [→](./x.ai/preview-dark.html) | [→](./x.ai/README.md) |
| [zapier](./zapier/) | Zapier automation | [→](./zapier/DESIGN.md) | [→](./zapier/preview.html) | [→](./zapier/preview-dark.html) | [→](./zapier/README.md) |

---

## Conventions

- Add new brands as `UI/<name>/` with the same trio when possible: `DESIGN.md`, `preview.html`, `preview-dark.html`, `README.md`.
- Image-heavy captures: prefer **not** committing huge binary dumps; use **Git LFS** or external storage if needed.
- Parent overview: [`.claw/design/README.md`](../README.md) · meta notes: [`Meta Aesthetics/`](../Meta%20Aesthetics/).

## Style selection metadata (for coder auto-pick)

- For scalable agent routing, each `DESIGN.md` can include optional frontmatter fields:
  - `styleTags`, `fitDomains`, `fitSurfaces`, `avoidSurfaces`, `toneKeywords`, `density`, `visualEnergy`.
- Add `tokens.compact.json` for high-frequency styles. Keep it tiny (core colors, radius, shadow, fonts).
- Optional: add global/per-style anti-patterns in `anti_patterns.json` for UI critic checks.
  - Supports legacy string list and object schema:
    - `pattern`, `severity`, `domains`, `surfaces`, `conflicts_with_tags`, `rewrite_hint`.
- Run `python scripts/build_ui_style_catalog.py` from workspace root to regenerate `UI/catalog.json`.
- Coder `/ui-style` mode uses this catalog for `list/show/auto/eval/why` instead of scanning all folders at runtime.
- Run proxy evaluation and CI gate from ClawCode workspace:
  - `py -3 scripts/run_ui_style_eval.py`
  - `py -3 scripts/run_ui_style_eval.py --ci-gate`

### Phase 3: batch frontmatter drafts

For brands that still lack YAML frontmatter, run from the **ClawCode workspace** (the directory that contains `.claw/`):

```bash
py -3 scripts/batch_ui_design_frontmatter.py
py -3 scripts/batch_ui_design_frontmatter.py --apply
```

- Default is **dry-run** (lists targets only). **`--apply`** prepends the template to each `UI/<slug>/DESIGN.md` that does **not** already start with `---`.
- The template fills **`title`** (from `# Design System: …` when possible) and **`role_hint`** from this README table; arrays start empty for human completion.
- After editing metadata, regenerate the index: `py -3 scripts/build_ui_style_catalog.py`.

**Section 1.5 stub (aesthetic fit):** for files that do not yet include `## 1.5 Aesthetic Fit & Use Cases`, insert a Markdown stub before `## 2. Color Palette & Roles` (aligned with the pilot brands):

```bash
py -3 scripts/batch_ui_design_section_15.py
py -3 scripts/batch_ui_design_section_15.py --apply
```

- Prefills **Best For** with `role_hint` from frontmatter when present; other subsections use `TODO_REVIEW` placeholders for human edit.
