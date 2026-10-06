# DSH / cordis 宿主适配说明

ZCode 桌面端与 dsh 等 DeepSeek Harness 系客户端共用同一套 **cordis 组合包机制**
(桌面端安装位置 `~/.dsh/profiles/desktop`,经 pnpm 安装 Git 仓库)。因此没有独立的
"适配层"——仓库根级就是一个可直接安装的组合包,与 ai-look-up 双端同构:

| 文件 | 作用 |
|---|---|
| `package.json` 的 `dsh.bundle.patch` | 声明组合包(缺了它客户端报"没有声明组合包,不能作为插件管理") |
| `cordis.patch.yml` | 向宿主插入 cordis 插件 `ai-residue-cleaner` |
| `index.js` | 宿主端逻辑(见下) |
| `hooks/hooks.json` + Python 钩子 | ZCode CLI 端(Stop/UserPromptSubmit 事件) |

## index.js 的宿主端职责

- `session/event` `user/message`:每个会话首条消息经 `agent.inject()` 注入一次输出守则(比 CLI 端每回合注入更省 KV-cache);
- `session/event` `turn/end`:**后台派生进程**运行 `hooks/cleanup.py --project <cwd>`(detached + `stdio: ignore`,不阻塞会话,python 缺失时静默降级)。

清运引擎自行判断项目状态(未立项常规清/open 跳过/结项走 close),宿主侧零判断逻辑。会话 cwd 的解析是防御性的:依次探测 `session.cwd / workspace / config.cwd / ctx.cwd`,拿不到或疑似宿主自身目录(`.dsh/`、`node_modules/`)就放弃本轮清运,绝不误扫。

## 配置项(cordis.patch.yml 的 config)

```yaml
- insert:
    - id: ai-residue-cleaner
      name: 'ai-residue-cleaner'
      config:
        enabled: true                # 总开关
        cleanupOnTurnEnd: true       # turn/end 自动清运
        brevityOnFirstMessage: true  # 首条消息注入输出守则
        pythonBin: python            # Python 解释器
```

## 验证状态(诚实声明)

JS bundle 的骨架(`apply(ctx, config)`、`agent/created`、`session/event`、`agent.inject`、
`agent.ctx.effect`)逐项对齐本机已验证运行的 ai-look-up v0.8.2,但本插件未在 dsh
运行时上实测;若 `session` 的 cwd 字段名与探测序列不符,清运会静默跳过(输出守则不受影响)。
