# AI 残渣清运 (ai-residue-cleaner)

AI 干完活,工地上到处是它留下的东西:探测脚本写了十几个(`_probe2.py`、`_probe3.py`、`_probe4.py`…),渲染出来的图、跑出来的结果、中途备份的目录,全堆在项目根目录。这个插件负责收拾:每回合结束自动把这类副产物收走,收到一个**可逆的回收站**里——不是删除,是移进 `.ai-residue-trash/<批次>/`,带清单,可以还原,14 天后才真删。

它还管两件相关的事:

- **项目制**。开工时用 `/residue-open` 声明一个产出目录,之后所有东西都往里放;没结项之前插件不清理,一切原地保留。结项时用 `/residue-close`:成品按类型归档(文稿、视频成品、音频、图片、数据),报告里引用的图片跟着报告走(引用路径自动改写,报告搬走后照样打得开),`*_results.txt` 这类之后可能还要翻的结果移进 `归档/`(长期保留,不进回收站),剩下的副产物进回收站,最后生成一份《结项清理清单》,写明哪些文件被收走了、收到了哪、去哪找回。
- **少说废话**。每个回合注入一条输出守则:直奔结论和新信息,不复述背景,不写空洞总结。

## 安装

**方式一:作为插件市场添加(ZCode / DeepSeek Harness 系客户端通用)**

客户端打开 **插件市场 → 添加 → 添加插件市场**,粘贴本仓库地址(或克隆到本地后选目录),然后在 **个人 → residue-cleaner-market** 里安装「AI 残渣清运」。

**方式二:Git 仓库直装(桌面端插件页)**

插件页直接粘贴 `https://github.com/1344738825/ai-residue-cleaner`。仓库同时是一个 cordis bundle,会以 Host 插件形式安装。

两种方式的差别:方式一走 Python 会话钩子(Stop / UserPromptSubmit),需要系统有 `python` 命令(3.8+,可执行名不同就改 `hooks/hooks.json` 里的 4 处);方式二走 JS bundle,回合结束时后台调一次 `cleanup.py`,机器上没有 Python 的话清运会静默跳过,守则注入不受影响。三个斜杠命令(`/residue-open`、`/residue-close`、`/residue-trash`)两种方式都有。

## 清运范围

- 草稿:项目根一层 `_*`(跳过 `__init__.py` 这类 `__*`)、`*_dryrun.txt`、`scratch*`
- 备份:任意层 `*backup*`(文件和目录)
- 临时:任意层 `*.tmp` `*.bak` `*.orig` `*.rej` `*~` `.DS_Store` `Thumbs.db`
- 日志:任意层 `*.log`
- 缓存目录:`__pycache__`、`.pytest_cache`、`.mypy_cache`、`.ruff_cache`、`.ipynb_checkpoints`

`*_results.txt`、`*_dump*` 这类之后可能要翻的结果默认**不**清(见上面归档);正式文档、报告也没有名字模式可猜,不动。

不碰的东西:`.git`、`node_modules`、`.zcode`、`.agents`、`.claude`、虚拟环境、嵌套 git 仓库(整个跳过,不弄脏别人的 git status)、以及项目根 `.ai-residue-ignore` 里列出的路径(一行一个 glob)。

## 配置

项目根 `.ai-residue.json`(可选):

```json
{
  "retention_days": 14,
  "extra_rules": [
    { "pattern": "probe*", "scope": "top", "target": "any", "category": "草稿" }
  ],
  "archive_dir": "归档",
  "archive_rules": [
    { "pattern": "*_dump*", "scope": "top" }
  ],
  "categories": { "视频成品": [".mp4", ".mov"] },
  "project": { "status": "open", "deliverables_dir": "产出" }
}
```

`project` 块由 `/residue-open` / `/residue-close` 维护,手改也行:`status: open` 时不自动清理,`closed` 恢复。

## 手动命令

```bash
python <插件目录>/hooks/cleanup.py --dry-run          # 预览将要收走什么
python <插件目录>/hooks/cleanup.py --force            # 项目 open 期间强制清一次
python <插件目录>/hooks/cleanup.py close --dry-run    # 结项流程预览
python <插件目录>/hooks/cleanup.py close              # 结项
python <插件目录>/hooks/cleanup.py status             # 回收站现状
python <插件目录>/hooks/cleanup.py restore latest     # 还原最近一批
```

## 说明

桌面端 / dsh 走 cordis 组合包(`package.json` 声明 `dsh.bundle.patch`),回合结束时后台清运,结构与 ai-look-up 同款;细节见 [adapters/dsh/README.md](adapters/dsh/README.md)。ZCode 自身日志缓存(`~/.zcode/cli/` 下)不在清运范围内。回收站目录建议加进版本库 `.gitignore`。
