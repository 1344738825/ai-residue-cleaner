# AI 残渣清运 (ai-residue-cleaner)

ZCode 插件 + DeepSeek Harness (cordis) 双端组合包:自动清运 AI 会话留下的副产物,并压制会话废话输出。支持**项目制**:产出固定目录、未结项前副产物保留、结项时归类成品 + 归档可引用结果 + 清运副产物 + 生成清理清单文本文档。

- **ZCode 桌面端 / dsh**:仓库根级就是组合包(`package.json` 的 `dsh.bundle.patch` 申明 + `cordis.patch.yml` + `index.js`),客户端直接从 Git 仓库安装;`turn/end` 后台清运,首条消息注入输出守则,详见 [adapters/dsh/README.md](adapters/dsh/README.md)。
- **ZCode CLI 端**:`hooks/hooks.json` + Python 钩子(Stop/UserPromptSubmit 事件)。

## 安装

**方式一:作为插件市场添加(ZCode / DeepSeek Harness 系客户端通用)**

仓库根目录即市场清单(`marketplace.json`,`source: "."`,与 ai-look-up 同构)。客户端里 **Plugin Marketplace → 添加 → 添加插件市场**,粘贴本仓库地址(Git URL 或本地目录),然后在 **个人 → residue-cleaner-market** 中安装「AI 残渣清运」。

**方式二:Git 仓库直装(桌面端插件页)**

插件页直接粘贴 `https://github.com/1344738825/ai-residue-cleaner`,客户端会以 cordis 组合包(`package.json` 的 `dsh.bundle.patch` 申明)把仓库装成 Host 插件。

两种方式的差异:

| | 方式一(市场) | 方式二(直装) |
|---|---|---|
| CLI 端 Python 钩子(Stop/UserPromptSubmit) | 生效 | 不生效 |
| 桌面/DSH 端 JS bundle(turn/end 后台清运 + 首条消息守则注入) | 生效 | 生效 |
| 依赖 | 需要系统 `python` 命令(3.8+;可执行名不同可改 `hooks/hooks.json` 4 处) | JS 端清运需要 `python`;缺失时清运静默跳过,守则注入不受影响 |

`/residue-open`、`/residue-close`、`/residue-trash` 三个命令随插件安装,两个方式都可用。

## 项目制

在项目根 `.ai-residue.json` 里声明:

```json
{
  "project": { "status": "open", "deliverables_dir": "产出" },
  "categories": { "视频成品": [".mp4", ".mov"] }
}
```

| 阶段 | 行为 |
|---|---|
| `/residue-open` 立项 | 写入 project 块(status=open),建产出目录;此后建议所有产物都放进该目录 |
| 项目进行中 | **自动清运暂停**,副产物原地保留;产出目录始终受保护,常规清运永不触碰 |
| `/residue-close` 结项 | ① 产出目录根一层成品按扩展名归类进子目录(默认 文稿/视频成品/音频/图片/数据,`categories` 可覆盖);**成品内的相对路径引用(图、资源)随成品搬入 `_assets/` 并改写引用,清运后成品仍自包含**;② 可引用的中间结果(`*_results.*`、`*_dump*` 等,`archive_rules` 可追加)移入归档目录(`archive_dir`,默认 `归档/`)——永不进回收站、不会真删;③ 清运其余副产物(**此时才包括产出目录内的**,未匹配成品类型的文件保持原位);④ 在产出目录写《结项清理清单-<时间>.txt》,逐项记录归类/归档/被删清单;⑤ status 置 closed,常规清运恢复 |

## 它做什么

| 钩子 | 事件 | 行为 |
|---|---|---|
| `cleanup.py` | `Stop` | 每回合结束,把项目里的 AI 副产物**移入**(不是删除)项目根的 `.ai-residue-trash/<时间戳>/`,并写 `manifest.json` 清单;保留期(默认 14 天)过后的回收批次自动真删。项目 open 期间跳过 |
| `brevity.py` | `UserPromptSubmit` | 每回合注入一条简短输出守则,减少复述背景、空洞总结、客套话 |

`/residue-trash` 命令:查看回收站现状、还原被清走的文件(可逆是底线)。

## 默认清理规则

- **草稿**:项目根一层 `_*`(排除 `__init__.py` 等 `__*`)、`*_results.txt/json`、`*_dryrun.txt`、`scratch*`
- **渲染图**:项目根一层 `page-*.png/jpg`、`render*.png/jpg`、`slide-*.png`
- **备份**:任意层 `*backup*`(文件和目录)
- **临时**:任意层 `*.tmp/*.temp/*.bak/*.orig/*.rej/*~/.DS_Store/Thumbs.db`
- **日志**:任意层 `*.log`
- **缓存目录**:`__pycache__`、`.pytest_cache`、`.mypy_cache`、`.ruff_cache`、`.ipynb_checkpoints`

永不进入 `.git`、`node_modules`、`.zcode`、`.agents`、`.claude`、虚拟环境和回收站自身。

## 按项目定制

- `.ai-residue-ignore`(项目根,一行一个 glob):命中的路径一律不碰,保护同名正牌文件。
- `.ai-residue.json`(项目根,可选):

```json
{
  "retention_days": 14,
  "extra_rules": [
    { "pattern": "probe*", "scope": "top", "target": "any", "category": "草稿" }
  ]
}
```

## 手动使用

```bash
python <插件目录>/hooks/cleanup.py --dry-run          # 预览将要移走什么
python <插件目录>/hooks/cleanup.py --force            # 项目 open 期间强制清一次
python <插件目录>/hooks/cleanup.py close --dry-run    # 结项流程预览
python <插件目录>/hooks/cleanup.py close              # 结项
python <插件目录>/hooks/cleanup.py status             # 回收站现状
python <插件目录>/hooks/cleanup.py restore latest     # 还原最近一批
```

## 其他宿主适配

- **DSH (DeepSeek Harness)**:[`adapters/dsh/`](adapters/dsh/README.md) — cordis patch 注入输出守则,收尾清运走 `cleanup.py --project`,见适配说明与验证状态。

## 说明

- 生成的文档/报告类交付物(如正式的 docx/pdf)没有安全的名字模式,默认**不**自动清;交给 ignore/extra_rules 或手动处理。
- ZCode 自身的日志与缓存(`~/.zcode/cli/` 下)出于安全不在本插件范围内。
- 回收站目录建议加入版本库的 `.gitignore`。
