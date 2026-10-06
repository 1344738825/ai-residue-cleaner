#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 残渣清运 · UserPromptSubmit 钩子。

每个工作回合注入一条简短的输出守则,压制会话里的废话输出
(复述已知背景、空洞总结、客套话、冗长教学段落)。
只输出 hookSpecificOutput/additionalContext,严格符合 hook 输出 schema。
"""

import json
import sys

RULE = ("【输出守则】回答直奔结论和新信息:不复述用户已知背景,不写客套话、"
        "空洞总结或教学铺垫;能用一句话说清就不用三句;除非用户明确要求,"
        "不主动生成报告、总结或逐条复述刚才做过的事。")


def main():
    try:
        sys.stdin.read()
    except OSError:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": RULE,
        }
    }, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
