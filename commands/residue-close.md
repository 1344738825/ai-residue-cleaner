---
description: 结项:归类最终产出、清运副产物,并生成记录被删文件的清单文档
---

为当前项目结项。先做预览,再实跑:

1. 确定插件引擎路径:优先找 `C:\Users\shenjingbing\.zcode\workspace\default\ai-residue-cleaner\hooks\cleanup.py`(开发市场安装源);找不到就问用户插件安装路径,或从 **Settings → Plugin Management → AI 残渣清运** 的详情页获取。以下命令中的 `CLEANUP` 均指该文件,`ROOT` 为项目根目录。
2. 确认项目根 `.ai-residue.json` 里有 `project` 块且 `status` 为 `open`;没有则先按 `/residue-open` 的约定补上。
3. **预览**(不动任何文件):

```bash
python "$CLEANUP" --project "$ROOT" close --dry-run
```

向用户汇报:将归类哪些成品、将清运哪些副产物。
4. 用户确认后**实跑**:

```bash
python "$CLEANUP" --project "$ROOT" close
```

5. 实跑完成后,读取产出目录里新生成的 `结项清理清单-<时间>.txt`,用简短汇报收尾:
   - 成品归类结果(哪些文件进了 文稿/视频成品/音频/图片/数据 哪个子目录,冲突跳过的要明确指出);
   - 本次删除(移入回收站)的副产物数量与代表性路径,提醒保留期 14 天、期间可用 `/residue-trash` 还原;
   - 项目状态已置为 `closed`,常规自动清运已恢复。
