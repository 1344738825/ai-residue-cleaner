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
 *   (detached + stdio ignore,绝不阻塞会话)。
 *
 * 清运引擎是 Python,所以解释器是硬前提:缺 Python 3 时不再静默跳过——写宿主 error
 * 日志,并在会话里提示一次(见 resolvePython / PYTHON_MISSING_NOTICE),
 * 否则用户界面上什么都看不到,会误以为清运成功了。
 *
 * 清运引擎(cleanup.py)自行判断项目状态:未立项/已结项按常规清,项目 open 期间
 * 自动跳过且产出目录受保护——宿主侧无需任何判断逻辑。
 *
 * 扩展点(见 cordis-plugin-development skill,与 ai-look-up 相同):
 * - `session/event`
 * - `agent.inject()`
 */

import { spawn, spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
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
  // 空 = 自动探测:按 PYTHON_CANDIDATES 顺序找第一个可用的 Python 3。
  // 显式填写(如 'python'、'C:/Python312/python.exe')则只认它,探不到就报错,不偷换解释器。
  pythonBin: '',
};

/**
 * 解释器候选,顺序即优先级。macOS 12+ 已不再自带 `python`,`python3` 才是常态;
 * Windows 上 `py` 启动器最稳,所以两个都排进候选。
 */
const PYTHON_CANDIDATES = process.platform === 'win32'
  ? ['python3', 'python', 'py']
  : ['python3', 'python'];

/** 探针:非 Python 3 解释器(python2)直接判负,cleanup.py 是 py3 语法。 */
const PROBE_ARGS = ['-c', 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)'];

/** 探测失败后重试的间隔:用户可能刚装好 Python,不必重启宿主。 */
const PYTHON_RETRY_MS = 10 * 60 * 1000;

let resolvedPython;      // undefined = 未探测 / null = 探测失败 / string = 可用解释器
let pythonProbedAt = 0;

function probePython(bin) {
  const name = typeof bin === 'string' ? bin.trim() : '';
  if (name === '') return false;
  try {
    const proc = spawnSync(name, PROBE_ARGS, { stdio: 'ignore', timeout: 5000, windowsHide: true });
    return proc.status === 0;   // 非 0:命令不存在、不是 python,或不是 Python 3
  } catch {
    return false;
  }
}

/**
 * 解析清运引擎用的解释器。命中一次就缓存(每进程只探一次);
 * 探测失败也缓存,但每 PYTHON_RETRY_MS 重试一次——避免每回合都 spawn 三次探针,
 * 也避免用户装好 Python 后还得重启宿主。
 */
function resolvePython(ctx, cfg) {
  if (typeof resolvedPython === 'string') return resolvedPython;
  const now = Date.now();
  if (resolvedPython === null && now - pythonProbedAt < PYTHON_RETRY_MS) return null;
  pythonProbedAt = now;
  const explicit = typeof cfg.pythonBin === 'string' && cfg.pythonBin.trim() !== '';
  const candidates = explicit ? [cfg.pythonBin] : PYTHON_CANDIDATES;
  for (const bin of candidates) {
    if (probePython(bin)) {
      resolvedPython = bin.trim();
      return resolvedPython;
    }
  }
  resolvedPython = null;
  ctx?.logger?.error?.(
    '[ai-residue-cleaner] 找不到可用的 Python 3(已尝试: %s)。清运 / 结项归类 / 回收站还原都不会执行,'
    + '直到解释器可用为止;把插件配置的 pythonBin 指向解释器绝对路径可跳过探测。',
    candidates.join(', '),
  );
  return null;
}

const PYTHON_MISSING_NOTICE = '【残渣清运】本机没有找到可用的 Python 3 解释器,清运引擎跑不起来:'
  + '本回合的草稿、备份、日志、缓存不会被收走,结项归类与回收站还原也用不了。'
  + '装上 Python 3,或在插件配置里把 pythonBin 指向解释器路径,下一回合自动恢复。';

/**
 * 把一条提示送进会话。宿主文档里 inject 收的是 UserMessage 对象;
 * 纯字符串在部分宿主版本会被存成读不回来的 payload,所以对象优先、字符串兜底。
 */
function deliverNotice(agent, text) {
  if (typeof agent?.inject !== 'function') return false;
  try {
    agent.inject({
      id: randomUUID(),
      role: 'user',
      content: [{ type: 'text', text }],
      source: { kind: 'plugin:ai-residue-cleaner' },
    });
    return true;
  } catch { /* 退回字符串形态 */ }
  try {
    agent.inject(text);
    return true;
  } catch {
    return false;
  }
}

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

function runCleanup(ctx, cfg, agent, st, session) {
  const cwd = sessionCwd(session);
  if (cwd === null) return;
  const pythonBin = resolvePython(ctx, cfg);
  if (pythonBin === null) {
    // 缺解释器不能静默:界面上必须看得见,否则用户会以为副产物已经被收走了
    if (st && !st.pythonWarned) {
      st.pythonWarned = true;
      deliverNotice(agent, PYTHON_MISSING_NOTICE);
    }
    return;
  }
  try {
    const child = spawn(pythonBin, [CLEANUP_SCRIPT, '--project', cwd], {
      cwd,
      detached: true,
      stdio: 'ignore',
      env: { ...process.env, CLAUDE_PROJECT_DIR: cwd, PYTHONIOENCODING: 'utf-8' },
    });
    // 起不来(权限、路径损坏等)要留证据:错误进宿主日志,不再是一句空 catch
    child.on('error', (error) => {
      ctx?.logger?.error?.('[ai-residue-cleaner] 清运进程启动失败(%s): %o', pythonBin, error);
    });
    child.unref();
  } catch (error) {
    ctx?.logger?.error?.('[ai-residue-cleaner] 清运进程派生失败: %o', error);
  }
}

export function apply(ctx, config) {
  const cfg = mergeConfig(config);
  if (!cfg.enabled) return;
  const agents = new Map(); // agent 对象 -> { brevityDone, pythonWarned }

  ctx.on('agent/created', (agent) => {
    agents.set(agent, { brevityDone: false, pythonWarned: false });
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
        runCleanup(ctx, cfg, agent, st, session);
      }
    } catch (error) {
      ctx?.logger?.warn?.('[ai-residue-cleaner] session event handling failed: %o', error);
    }
  });
}

/** Test-only internals (no runtime consumers). */
export const __test = { probePython, resolvePython, PYTHON_CANDIDATES };
