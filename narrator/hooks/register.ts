import type { Register } from 'claude-code'

const PYTHON = '/usr/bin/python3'

// Tools that stop and wait for the person: a question dialog, a plan to approve.
const WAITING_TOOLS = /^(AskUserQuestion|ExitPlanMode)$/

// A reply whose last line ends in a question is waiting on the person.
const asksSomething = (answer: string) => /\?[*_`'")\]\s]*$/.test(answer.trim())

// /narrator actions that run a shell script instead of voice_claude.py.
const SCRIPTS: Record<string, string> = { setup: 'install.sh', uninstall: 'uninstall.sh' }

export const register: Register = (on) => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'narrator',
      description: 'Narrator: hear replies in a chosen voice with Control+Option+R',
      argumentHint: 'status | read | stop | use <name> | add <name> <voice-id> | detail short|medium|full | flash on|off|<seconds> | test | setup | uninstall',
    })

    return next(e)
  })

  // When Claude finishes answering, flash the screen if the person is away
  // (orange when done, blue when the reply asks them something) and write the
  // summary ahead, so the hotkey can speak it at once. Subagent turns and
  // interrupted ones are left alone.
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (!e.agentId && e.reason === 'answer' && e.answer.trim()) {
      const kind = asksSomething(e.answer) ? 'ask' : 'done'
      void $.process
        .run([PYTHON, `${$.plugin.root}/voice_claude.py`, 'on-stop', kind], { stdin: '{}', timeoutMs: 10_000 })
        .catch(() => undefined)
    }

    return result
  })

  // A question dialog or plan approval mid-turn: flash blue if the person is away.
  on('tool.call', { tool: WAITING_TOOLS }, async ($, e, next) => {
    void $.process
      .run([PYTHON, `${$.plugin.root}/voice_claude.py`, 'alert'], { timeoutMs: 10_000 })
      .catch(() => undefined)

    return next(e)
  })

  on('command.run', { command: 'narrator' }, async ($, e) => {
    const [action = 'status', ...args] = e.args.trim().split(/\s+/).filter(Boolean)
    try {
      const script = SCRIPTS[action]
      if (script) {
        const { exitCode, stdout, stderr } = await $.process.run(
          ['/bin/bash', `${$.plugin.root}/${script}`],
          { timeoutMs: 300_000 },
        )
        return { text: exitCode === 0 ? stdout.trim() : `/narrator ${action} failed:\n${(stderr || stdout).trim()}` }
      }
      const argv = [PYTHON, `${$.plugin.root}/voice_claude.py`, action, ...args]
      if (action === 'read') argv.push('--detach')
      const { stdout, stderr } = await $.process.run(argv, { timeoutMs: 60_000 })

      return { text: (stdout || stderr).trim() || 'Done.' }
    } catch (error) {
      return { text: `/narrator ${action} failed:${error instanceof Error ? error.message : String(error)}` }
    }
  })
}
