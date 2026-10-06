# DSH (DeepSeek Harness) 适配层

DSH 的扩展面是 cordis 插件 + `cordis.patch.yml`,目前**没有**文档化的会话结束 hook 事件,所以适配方式与 ZCode 端不同:

| 能力 | ZCode 端 | DSH 端 |
|---|---|---|
| 废话抑制 | `UserPromptSubmit` 钩子注入 | `personaSuffix` patch 追加同一条守则(与 `dsh-acp-app` 的 `system-prompt` patch 同款通道) |
| 收尾清运 | `Stop` 钩子自动执行 | patch 里写一条确定性指令:收尾时运行 `python cleanup.py --project "{{cwd}}"`;引擎显式支持 `--project`,不依赖 ZCode 的 stdin/env 约定 |

## 接入

把 [`cordis.patch.yml`](./cordis.patch.yml) 里的条目合并进你的 profile patch(条目 id 均带 `residue-cleaner-` 前缀,不会撞名),并把其中的 `<本插件安装路径>` 替换为本插件的实际安装目录。

## 诚实声明

- `personaSuffix` 通道已在 `@deepseek-ai/dsh-acp-app` 的官方 patch 中使用,可靠。
- 收尾清运走的是提示词指令,不是宿主级生命周期钩子——如果 dsh 之后开放 session stop 类事件给插件,引擎侧无需改动(`python cleanup.py --project <dir>` 本身无 stdin/env 依赖),届时把指令换成真正的事件调用即可。
- 本适配层未在真实 dsh profile 上验证过(本机没有可用的 dsh 运行时);patch 语法与 `dsh-acp-app` 0.2.0-rc.2 的结构一致。
