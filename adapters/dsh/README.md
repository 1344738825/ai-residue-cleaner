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
- `session/event` `turn/end`:**后台派生进程**运行 `hooks/cleanup.py --project <cwd>`(detached + `stdio: ignore`,不阻塞会话;解释器缺失时写 `error` 日志并在会话里提示一次,不再静默降级)。

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
        pythonBin: ''                # 留空=自动探测 python3→python→py;填了只认它
```

解释器解析(`index.js` 的 `resolvePython`):留空时按平台候选顺序逐个跑探针
`python -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)"`,第一个返回 0 的胜出并缓存;
显式配置 `pythonBin` 时只认它,不偷偷换成别的解释器。全部失败则拒绝清运(不 spawn 半残命令),
同时在宿主日志留一条 `error` 并在会话里提示一次;失败结果缓存 10 分钟后重试,装好 Python 无需重启宿主。

## 验证状态(诚实声明)

JS bundle 的骨架(`apply(ctx, config)`、`agent/created`、`session/event`、`agent.inject`、
`agent.ctx.effect`)逐项对齐本机已验证运行的 ai-look-up v0.8.2,但本插件未在 dsh
运行时上实测;若 `session` 的 cwd 字段名与探测序列不符,清运会静默跳过(输出守则不受影响)。
解释器探测与缺失提示在 Node 22 上单独跑过冒烟(命中 `python3`、以及显式指向不存在的解释器时
日志+提示各一次),宿主内的事件链仍未实测。
