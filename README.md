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

两种方式的差别:方式一走 Python 会话钩子(Stop / UserPromptSubmit),需要系统有 `python` 命令(3.8+,可执行名不同就改 `hooks/hooks.json` 里的 2 处);方式二走 JS bundle,回合结束时后台调一次 `cleanup.py`,需要**系统里有 Python 3**——插件按 `python3` → `python` → `py`(Windows)顺序自动探测,探不到就跳过清运、写宿主错误日志,并在会话里明确提示一次(不会静默),守则注入始终不受影响。三个斜杠命令(`/residue-open`、`/residue-close`、`/residue-trash`)两种方式都有。

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

### 宿主侧配置(桌面端 / dsh)

组合包的 `config`(见 `cordis.patch.yml`)有四个配置项,其中解释器这一项值得说清楚:

```yaml
config:
  pythonBin: ''      # 留空 = 自动探测;填了则只认它(可写绝对路径)
```

留空时按 `python3` → `python` → `py`(仅 Windows)顺序找第一个**可用的 Python 3**(会实际跑一次 `sys.version_info[0] == 3` 探针,Python 2 不算数),命中后缓存,之后每回合直接复用。探测失败时:

- 清运不会执行(`cleanup.py` 跑不起来,结项归类、回收站还原同样不可用);
- 宿主日志里留下一条 `error`(写明试过哪些候选);
- 会话里提示一次,说明原因和恢复办法——**不再静默跳过**;
- 装好 Python 后不必重启宿主,十分钟内会自动重试探测;
- 输出守则注入是与 Python 无关的纯 JS 路径,始终正常。

## 手动命令

```bash
python <插件目录>/hooks/cleanup.py --dry-run          # 预览将要收走什么
python <插件目录>/hooks/cleanup.py --force            # 项目 open 期间强制清一次
python <插件目录>/hooks/cleanup.py close --dry-run    # 结项流程预览
python <插件目录>/hooks/cleanup.py close              # 结项
python <插件目录>/hooks/cleanup.py status             # 回收站现状
python <插件目录>/hooks/cleanup.py restore latest     # 还原最近一批
```

上面这些命令要自己敲,名字按你机器上的来(`python3` / `py` 均可,插件目录指装好的包目录)。

## 说明

桌面端 / dsh 走 cordis 组合包(`package.json` 声明 `dsh.bundle.patch`),回合结束时后台清运,结构与 ai-look-up 同款;细节见 [adapters/dsh/README.md](adapters/dsh/README.md)。**前提是这台机器上有 Python 3**(见上方「宿主侧配置」)。ZCode 自身日志缓存(`~/.zcode/cli/` 下)不在清运范围内。回收站目录建议加进版本库 `.gitignore`。
