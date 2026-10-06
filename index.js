/**
 * AI 残渣清运 — Host plugin for the DeepSeek Harness (cordis bundle).
 *
 * 与 ZCode CLI 端的 hooks/ Python 钩子同源双端:本 bundle 服务 cordis 系宿主
 * (ZCode 桌面端、dsh),结构对齐 ai-look-up 的既有实践。
 *
 * 职责:
 * - `session/event` `user/message`: 每个会话首条消息注入一次输出守则(agent.inject),
 *   压制复述背景、空洞总结、客套话;
 * - `session/event` `turn/end`: 后台派生进程运行 hooks/cleanup.py 按项目制清运副产物
 *   (detached + stdio ignore,绝不阻塞会话;清运失败静默降级)。
 *
 * 清运引擎(cleanup.py)自行判断项目状态:未立项/已结项按常规清,项目 open 期间
 * 自动跳过且产出目录受保护——宿主侧无需任何判断逻辑。
 *
 * 扩展点(见 cordis-plugin-development skill,与 ai-look-up 相同):
 * - `session/event`
 * - `agent.inject()`
 */

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';

const PLUGIN_ROOT = dirname(fileURLToPath(import.meta.url));
const CLEANUP_SCRIPT = join(PLUGIN_ROOT, 'hooks', 'cleanup.py');

const BREVITY_RULE = '【输出守则】回答直奔结论和新信息:不复述用户已知背景,不写客套话、空洞总结或教学铺垫;能用一句话说清就不用三句;除非用户明确要求,不主动生成报告、总结或逐条复述刚才做过的事。';

const DEFAULTS = {
  enabled: true,
  cleanupOnTurnEnd: true,
  brevityOnFirstMessage: true,
  pythonBin: 'python',
};

function mergeConfig(config) {
  const out = { ...DEFAULTS };
  if (config && typeof config === 'object') {
    for (const key of Object.keys(DEFAULTS)) {
      if (config[key] !== undefined) out[key] = config[key];
    }
  }
  return out;
}

/**
 * 从 session 上尽力解析项目根目录。探测顺序是防御性的:宿主字段名可能随版本变化,
 * 任何候选解析失败都降级到下一个;最终拿不到就放弃本轮清运,绝不误扫宿主目录。
 */
function sessionCwd(session) {
  const candidates = [session?.cwd, session?.workspace, session?.config?.cwd, session?.ctx?.cwd];
  for (const candidate of candidates) {
    if (typeof candidate !== 'string' || candidate.length === 0) continue;
    try {
      const p = resolve(candidate);
      if (!existsSync(p)) continue;
      const norm = p.replaceAll('\\', '/').toLowerCase();
      if (norm.includes('/.dsh/') || norm.includes('/node_modules/')) continue;
      return p;
    } catch { /* 下一个候选 */ }
  }
  return null;
}

function runCleanup(cfg, session) {
  const cwd = sessionCwd(session);
  if (cwd === null) return;
  try {
    const child = spawn(cfg.pythonBin, [CLEANUP_SCRIPT, '--project', cwd], {
      cwd,
      detached: true,
      stdio: 'ignore',
      env: { ...process.env, CLAUDE_PROJECT_DIR: cwd, PYTHONIOENCODING: 'utf-8' },
    });
    child.on('error', () => { /* python 缺失等,静默降级 */ });
    child.unref();
  } catch { /* 清运失败不影响会话 */ }
}

export function apply(ctx, config) {
  const cfg = mergeConfig(config);
  if (!cfg.enabled) return;
  const agents = new Map(); // agent 对象 -> { brevityDone }

  ctx.on('agent/created', (agent) => {
    agents.set(agent, { brevityDone: false });
    try {
      agent.ctx?.effect?.(() => () => agents.delete(agent));
    } catch (error) {
      ctx?.logger?.warn?.('[ai-residue-cleaner] agent cleanup registration failed: %o', error);
    }
  });

  ctx.on('session/event', (session, event) => {
    try {
      let agent = null;
      for (const [key] of agents) {
        if (key?.session === session) { agent = key; break; }
      }
      if (agent === null) return;
      const st = agents.get(agent);
      if (event?.type === 'user/message') {
        if (cfg.brevityOnFirstMessage && !st.brevityDone
            && typeof agent.inject === 'function') {
          st.brevityDone = true;
          try {
            agent.inject(BREVITY_RULE);
          } catch (error) {
            ctx?.logger?.warn?.('[ai-residue-cleaner] agent.inject failed: %o', error);
          }
        }
        return;
      }
      if (event?.type === 'turn/end' && cfg.cleanupOnTurnEnd) {
        runCleanup(cfg, session);
      }
    } catch (error) {
      ctx?.logger?.warn?.('[ai-residue-cleaner] session event handling failed: %o', error);
    }
  });
}
