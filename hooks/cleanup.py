#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 残渣清运 · Stop 钩子。

把会话期间 AI 留下的副产物(草稿脚本、探测输出、渲染图片、备份目录、
日志、缓存目录)从项目里移进可逆的回收站目录 `.ai-residue-trash/`,
不直接删除;每次搬运写清单,超过保留期(默认 14 天)的回收站才真删。

用法:
  python cleanup.py             hook 模式(读 stdin,清完后不输出任何 stdout)
  python cleanup.py --dry-run   只打印将要移动的条目,不动文件
  python cleanup.py --force     项目 open 期间也强制清一次(平时不需要)
  python cleanup.py close       结项:归类成品 → 清运副产物 → 写结项清理清单
  python cleanup.py close --dry-run   结项流程预览,不动文件、不改状态
  python cleanup.py status      汇报回收站现状
  python cleanup.py restore latest   把最近一次搬走的文件放回原位
  python cleanup.py restore <run-id> 同上,按批次名(如 20261006-153001)
所有模式都支持 --project <项目根目录>。

项目制(.ai-residue.json 的 project 块):
  {"project": {"status": "open", "deliverables_dir": "产出"}}
  status=open 时 Stop 钩子不自动清运(副产物原地保留),产出目录始终受保护;
  close 时把产出目录根一层的成品按扩展名归入分类子目录(默认
  文稿/视频成品/音频/图片/数据,可用 "categories" 覆盖),再清运全部副产物,
  并在产出目录写《结项清理清单-<时间>.txt》记录被删文件,最后 status 置 closed。

保护规则:
  - 永不进入 .git / node_modules / .zcode / .agents / .claude / 虚拟环境;
  - `_*` 草稿规则跳过 `__*`(保护 __init__.py 之类正经源码);
  - 项目根的 `.ai-residue-ignore`(glob,一行一个)里的路径一律跳过;
  - `.ai-residue.json` 可扩展规则、调整保留期。
"""

import json
import os
import re
import shutil
import sys
import time
from fnmatch import fnmatch
from pathlib import Path

TRASH_NAME = ".ai-residue-trash"
IGNORE_NAME = ".ai-residue-ignore"
CONFIG_NAME = ".ai-residue.json"
RETENTION_DAYS = 14

# 永不进入、也永不搬动的目录名
PROTECTED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".zcode", ".agents", ".claude",
    ".venv", "venv", "env", ".idea", ".vscode", TRASH_NAME,
}

# (类别, 目标类型 file|dir|any, glob, 范围 top|tree)
DEFAULT_RULES = [
    ("草稿",   "any",  "_*",             "top"),   # _probe.py / _peek2.png / _dsh_acp …
    ("草稿",   "file", "*_results.txt",  "top"),
    ("草稿",   "file", "*_results.json", "top"),
    ("草稿",   "file", "*_dryrun.txt",   "top"),
    ("草稿",   "any",  "scratch*",       "top"),
    ("渲染图", "file", "page[-_]*.png",  "top"),
    ("渲染图", "file", "page[-_]*.jpg",  "top"),
    ("渲染图", "file", "render*.png",    "top"),
    ("渲染图", "file", "render*.jpg",    "top"),
    ("渲染图", "file", "slide[-_]*.png", "top"),
    ("备份",   "any",  "*backup*",       "tree"),  # md_pipeline_backup_* 这类
    ("临时",   "file", "*.tmp",          "tree"),
    ("临时",   "file", "*.temp",         "tree"),
    ("临时",   "file", "*.bak",          "tree"),
    ("临时",   "file", "*.orig",         "tree"),
    ("临时",   "file", "*.rej",          "tree"),
    ("临时",   "file", "*~",             "tree"),
    ("临时",   "file", ".DS_Store",      "tree"),
    ("临时",   "file", "Thumbs.db",      "tree"),
    ("日志",   "file", "*.log",          "tree"),
    ("缓存",   "dir",  "__pycache__",    "tree"),
    ("缓存",   "dir",  ".pytest_cache",  "tree"),
    ("缓存",   "dir",  ".mypy_cache",    "tree"),
    ("缓存",   "dir",  ".ruff_cache",    "tree"),
    ("缓存",   "dir",  ".ipynb_checkpoints", "tree"),
]


def load_config(project: Path):
    cfg = {
        "retention_days": RETENTION_DAYS,
        "extra_rules": [],
        "project": None,        # {"status": "open"|"closed", "deliverables_dir": "产出"}
        "categories": None,     # 结项归类映射,覆盖默认: {"文稿": [".docx", ...], ...}
    }
    path = project / CONFIG_NAME
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("retention_days"), (int, float)) and data["retention_days"] >= 0:
                cfg["retention_days"] = int(data["retention_days"])
            if isinstance(data.get("extra_rules"), list):
                cfg["extra_rules"] = [r for r in data["extra_rules"] if isinstance(r, dict) and r.get("pattern")]
            if isinstance(data.get("project"), dict):
                cfg["project"] = data["project"]
            if isinstance(data.get("categories"), dict):
                cfg["categories"] = data["categories"]
        except (ValueError, OSError) as exc:
            note(stderr, "配置文件读取失败,使用默认规则: %s" % exc)
    return cfg


def project_open(cfg) -> bool:
    proj = cfg.get("project") or {}
    return proj.get("status") == "open"


def output_rel(cfg) -> str | None:
    """产出目录(相对项目根)。配置了 project 块才生效。"""
    proj = cfg.get("project") or {}
    name = proj.get("deliverables_dir") or "产出"
    return name.strip("/\\") or None


def in_output(rel: str, out_rel: str | None) -> bool:
    return bool(out_rel) and (rel == out_rel or rel.startswith(out_rel.replace("\\", "/") + "/"))


# 结项归类:默认按扩展名;可在 .ai-residue.json 用 "categories" 覆盖
DEFAULT_CATEGORIES = [
    ("文稿",     {".docx", ".doc", ".pdf", ".txt", ".md", ".wps", ".odt", ".rtf"}),
    ("视频成品", {".mp4", ".mov", ".mkv", ".avi", ".webm"}),
    ("音频",     {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}),
    ("图片",     {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}),
    ("数据",     {".csv", ".xlsx", ".xls", ".json", ".sqlite", ".db"}),
]
REPORT_PREFIX = "结项清理清单"


def note(stream, text):
    stream.write(text.rstrip() + "\n")
    stream.flush()


def load_ignores(project: Path):
    path = project / IGNORE_NAME
    patterns = []
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        except OSError:
            pass
    return patterns


def is_ignored(rel: str, name: str, ignores):
    return any(fnmatch(rel, p) or fnmatch(name, p) for p in ignores)


def iter_tree(project: Path, pattern: str):
    """按 pattern 收集 tree 范围条目;不进保护目录,不越过嵌套 git 仓库边界。"""
    stack = [project]
    while stack:
        directory = stack.pop()
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name in PROTECTED_DIRS or (child / ".git").exists():
                    continue
                if fnmatch(child.name, pattern):
                    yield child          # 整目录被搬走,不再下钻
                else:
                    stack.append(child)
            elif fnmatch(child.name, pattern):
                yield child


def iter_candidates(project: Path, ignores, out_rel=None, include_output=False):
    """产出 (路径, 类别, 相对路径)。不进保护目录,规则命中即停。

    配置了产出目录时,默认整个产出目录受保护(include_output=True 仅限结项清运用)。
    """
    for category, target, pattern, scope in DEFAULT_RULES:
        if scope == "top":
            # top 范围:只看项目根一层;_* 之外的 glob 直接取,统一排除 __*
            entries = [p for p in project.glob(pattern) if not p.name.startswith("__")]
        else:
            entries = list(iter_tree(project, pattern))
        for entry in entries:
                try:
                    rel = entry.relative_to(project).as_posix()
                except ValueError:
                    continue
                if entry == project:
                    continue
                if scope == "top" and entry.parent != project:
                    continue
                if target == "file" and not entry.is_file():
                    continue
                if target == "dir" and not entry.is_dir():
                    continue
                if not include_output and in_output(rel, out_rel):
                    continue
                if is_ignored(rel, entry.name, ignores):
                    continue
                yield entry, category, rel


def collect(project: Path, ignores, out_rel=None, include_output=False):
    """去重地收集所有命中条目。"""
    cfg = load_config(project)
    if out_rel is None:
        out_rel = output_rel(cfg)
    seen = {}
    for entry, category, rel in iter_candidates(project, ignores, out_rel, include_output):
        if rel in seen:
            continue
        seen[rel] = (entry, category)
    for rule in cfg["extra_rules"]:
        scope = rule.get("scope", "top")
        target = rule.get("target", "any")
        pattern = rule["pattern"]
        category = rule.get("category", "自定义")
        if scope == "top":
            candidates = [p for p in project.glob(pattern) if not p.name.startswith("__")]
        else:
            candidates = list(iter_tree(project, pattern))
        for entry in candidates:
            if entry == project or not entry.exists():
                continue
            if scope == "top" and entry.parent != project:
                continue
            if target == "file" and not entry.is_file():
                continue
            if target == "dir" and not entry.is_dir():
                continue
            try:
                rel = entry.relative_to(project).as_posix()
            except ValueError:
                continue
            if rel in seen or is_ignored(rel, entry.name, ignores):
                continue
            if not include_output and in_output(rel, out_rel):
                continue
            seen[rel] = (entry, category)
    return seen, cfg


stderr = sys.stderr


def clean(project: Path, dry_run: bool = False, force: bool = False,
          include_output: bool = False):
    """常规清运。项目 open 期间直接跳过(副产物保留),除非 force/结项专用路径。"""
    cfg0 = load_config(project)
    if project_open(cfg0) and not force and not dry_run:
        note(stderr, "残渣清运:项目未结项,副产物原地保留(结项请用 close)。")
        return None
    seen, cfg = collect(project, load_ignores(project), include_output=include_output)
    if not seen:
        return None
    if dry_run:
        for rel, (entry, category) in sorted(seen.items()):
            note(sys.stdout, "[dry-run] %-4s %s" % (category, rel))
        note(sys.stdout, "共 %d 项" % len(seen))
        return

    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = project / TRASH_NAME / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "project": str(project), "items": []}
    moved = []
    for rel, (entry, category) in sorted(seen.items()):
        if not entry.exists():
            continue
        # 祖先目录已整体入站,后代随它一起走,不必也无法单独搬
        if any(rel == m or rel.startswith(m + "/") for m in moved):
            continue
        dest = run_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(entry), str(dest))
            manifest["items"].append({"src": rel, "category": category})
            moved.append(rel)
        except (shutil.Error, OSError) as exc:
            note(stderr, "残渣清运:跳过 %s (%s)" % (rel, exc))
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    latest = project / TRASH_NAME / "latest.json"
    latest.write_text(json.dumps({"run": run_id, **manifest}, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    with (project / TRASH_NAME / "runs.log").open("a", encoding="utf-8") as fh:
        fh.write("%s\t%d items\n" % (run_id, len(manifest["items"])))
    purge(project, cfg["retention_days"])


def purge(project: Path, retention_days: int):
    if retention_days <= 0:
        return
    cutoff = time.time() - retention_days * 86400
    trash = project / TRASH_NAME
    if not trash.is_dir():
        return
    for run_dir in trash.iterdir():
        if not run_dir.is_dir() or not re.fullmatch(r"\d{8}-\d{6}", run_dir.name):
            continue
        try:
            stamp = time.mktime(time.strptime(run_dir.name, "%Y-%m%d-%H%M%S"))
        except ValueError:
            continue
        if stamp < cutoff:
            shutil.rmtree(run_dir, ignore_errors=True)


def classify_output(project: Path, cfg, dry_run: bool):
    """结项第一步:把产出目录根一层的成品按扩展名归入分类子目录。

    返回 (归类成功的 [(文件名, 分类)], 冲突跳过的 [(文件名, 分类)])。
    目录、清单文件本身、无匹配扩展名的文件一律不动。
    """
    out_rel = output_rel(cfg)
    if not out_rel:
        return [], []
    out_dir = project / out_rel
    if not out_dir.is_dir():
        return [], []
    if cfg.get("categories"):
        categories = [(name, {e.lower() for e in exts})
                      for name, exts in cfg["categories"].items()]
    else:
        categories = DEFAULT_CATEGORIES
    moved, skipped = [], []
    for entry in sorted(out_dir.iterdir()):
        if not entry.is_file() or entry.is_symlink():
            continue
        if entry.name.startswith(REPORT_PREFIX):
            continue
        ext = entry.suffix.lower()
        for cat_name, exts in categories:
            if ext not in exts:
                continue
            dest_dir = out_dir / cat_name
            dest = dest_dir / entry.name
            if dest.exists():
                skipped.append((entry.name, cat_name))
                break
            if dry_run:
                moved.append((entry.name, cat_name))
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(entry), str(dest))
                    moved.append((entry.name, cat_name))
                except (shutil.Error, OSError) as exc:
                    note(stderr, "残渣清运:归类失败 %s (%s)" % (entry.name, exc))
            break
    return moved, skipped


def close_project(project: Path, dry_run: bool = False):
    """结项:归类成品 → 清运副产物(含产出目录内) → 写清理清单 → 标记 closed。"""
    cfg = load_config(project)
    out_rel = output_rel(cfg)
    classified, conflicts = classify_output(project, cfg, dry_run)

    trash_runs_before = set()
    trash = project / TRASH_NAME
    if trash.is_dir():
        trash_runs_before = {d.name for d in trash.iterdir() if d.is_dir()}

    clean(project, dry_run=dry_run, force=True, include_output=True)

    # 找出本次结项产生的回收站批次(可能没有:没有副产物)
    swept = []
    run_id = None
    if not dry_run and trash.is_dir():
        new_runs = {d.name for d in trash.iterdir() if d.is_dir()} - trash_runs_before
        for name in sorted(new_runs):
            try:
                data = json.loads((trash / name / "manifest.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            run_id = name
            swept = [(it["src"], it.get("category", "?")) for it in data.get("items", [])]

    if not dry_run:
        report = build_close_report(cfg, classified, conflicts, swept, run_id)
        if out_rel:
            report_path = project / out_rel / ("%s-%s.txt" % (REPORT_PREFIX, time.strftime("%Y%m%d-%H%M%S")))
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report, encoding="utf-8-sig")
            note(sys.stdout, "残渣清运:清单已写入 %s" % report_path)
        else:
            note(sys.stdout, report)
        set_project_status(project, "closed")
        note(sys.stdout, "残渣清运:项目已标记为 closed,常规自动清运恢复。")
    else:
        seen, _ = collect(project, load_ignores(project), include_output=True)
        note(sys.stdout, "[dry-run] 归类 %d 项,清运 %d 项" % (len(classified), len(seen)))
    return classified, swept


def build_close_report(cfg, classified, conflicts, swept, run_id):
    lines = []
    lines.append("结项清理清单  %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("=" * 46)
    lines.append("")
    lines.append("一、成品归类(产出目录根一层 → 分类子目录)")
    if classified:
        for name, cat in classified:
            lines.append("  %-8s ← %s" % (cat, name))
    else:
        lines.append("  (无可归类的成品)")
    for name, cat in conflicts:
        lines.append("  [冲突跳过] %s → %s(目标位置已有同名文件,请手动处理)" % (name, cat))
    lines.append("")
    lines.append("二、本次删除的副产物(移入回收站,未直接删除)")
    if swept:
        lines.append("  回收站批次: %s" % (run_id or "?"))
        for rel, cat in swept:
            lines.append("  [%s] %s" % (cat, rel))
        lines.append("  共 %d 项。保留期 %d 天,过期由插件自动真删;" % (len(swept), cfg["retention_days"]))
        lines.append("  在此之前可在 .ai-residue-trash/%s/ 中找回,或用 /residue-trash 还原。" % (run_id or "?"))
    else:
        lines.append("  (本次没有副产物需要清运)")
    lines.append("")
    lines.append("三、说明")
    lines.append("  - 文件只是被移入项目根的 .ai-residue-trash/,结项当下不删除任何内容;")
    lines.append("  - 产出目录内未匹配任何成品类型的文件保持原位,未做处理;")
    lines.append("  - 恢复常规自动清运:项目状态已置为 closed。")
    return "\n".join(lines) + "\n"


def set_project_status(project: Path, status: str):
    path = project / CONFIG_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    proj = data.get("project") if isinstance(data.get("project"), dict) else {}
    proj["status"] = status
    data["project"] = proj
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_status(project: Path):
    out = sys.stdout
    trash = project / TRASH_NAME
    if not trash.is_dir():
        note(out, "回收站不存在,当前没有已清运的残渣。")
        return
    runs = sorted(d.name for d in trash.iterdir() if d.is_dir() and re.fullmatch(r"\d{8}-\d{6}", d.name))
    total = 0
    for run in runs:
        manifest_path = trash / run / "manifest.json"
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data.get("items", [])
        total += len(items)
        by_cat = {}
        for it in items:
            by_cat[it.get("category", "?")] = by_cat.get(it.get("category", "?"), 0) + 1
        note(out, "%s  %d 项  %s" % (run, len(items),
             "  ".join("%s:%d" % kv for kv in sorted(by_cat.items()))))
    note(out, "共 %d 个批次、%d 项(保留期 %d 天,过期自动真删)" % (
        len(runs), total, load_config(project)["retention_days"]))


def cmd_restore(project: Path, run_id: str):
    run_dir = project / TRASH_NAME / run_id
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        note(sys.stderr, "找不到批次 %s 的清单(%s)" % (run_id, manifest_path))
        sys.exit(2)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored, skipped = 0, 0
    for item in data.get("items", []):
        src = run_dir / item["src"]
        dst = project / item["src"]
        if not src.exists():
            skipped += 1
            continue
        if dst.exists():
            note(sys.stderr, "原位置已存在同名文件,跳过: %s" % item["src"])
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        restored += 1
    note(sys.stdout, "已还原 %d 项,跳过 %d 项(批次 %s)。" % (restored, skipped, run_id))
    if restored:
        left = [p.name for p in run_dir.iterdir() if p.name != "manifest.json"]
        if not left:
            # 全部还原且只剩清单,批次目录连同清单一起移除
            (run_dir / "manifest.json").unlink(missing_ok=True)
            run_dir.rmdir()


def main():
    args = sys.argv[1:]
    # 提取 --project <dir> / --project=<dir>,宿主无关的显式指定入口
    project_arg = None
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args):
            project_arg = args[i + 1]
            i += 2
        elif args[i].startswith("--project="):
            project_arg = args[i].split("=", 1)[1]
            i += 1
        else:
            rest.append(args[i])
            i += 1
    args = rest

    project = None
    if project_arg and Path(project_arg).is_dir():
        project = Path(project_arg)
    if project is None:
        for value in (os.environ.get("CLAUDE_PROJECT_DIR"), os.environ.get("ZCODE_PROJECT_DIR")):
            if value and Path(value).is_dir():
                project = Path(value)
                break
    if project is None:
        try:
            hook_input = json.loads(sys.stdin.read() or "{}")
            cwd = hook_input.get("cwd") or hook_input.get("project_dir")
            if cwd and Path(cwd).is_dir():
                project = Path(cwd)
        except ValueError:
            pass
    if project is None:
        project = Path.cwd()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if "close" in args:
        close_project(project, dry_run="--dry-run" in args)
    elif args[:1] == ["--dry-run"]:
        clean(project, dry_run=True)
    elif args[:1] == ["status"]:
        cmd_status(project)
    elif args[:1] == ["restore"]:
        run_id = args[1] if len(args) > 1 else "latest"
        if run_id == "latest":
            latest = project / TRASH_NAME / "latest.json"
            try:
                run_id = json.loads(latest.read_text(encoding="utf-8"))["run"]
            except (OSError, ValueError, KeyError):
                note(sys.stderr, "没有可还原的批次。")
                sys.exit(2)
        cmd_restore(project, run_id)
    else:
        clean(project, dry_run=False, force="--force" in args)
    sys.exit(0)


if __name__ == "__main__":
    main()
