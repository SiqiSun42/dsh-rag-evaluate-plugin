import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync, realpathSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const pkgDir = dirname(realpathSync(fileURLToPath(import.meta.url)))
const isWindows = process.platform === 'win32'
const venvDir = join(pkgDir, '.venv')
const pythonBin = isWindows
  ? join(venvDir, 'Scripts', 'python.exe')
  : join(venvDir, 'bin', 'python')
const requirementsPath = join(pkgDir, 'requirements.txt')
const stampPath = join(venvDir, '.requirements.sha256')
const bootPython = process.env.RAG_EVALUATE_PYTHON || (isWindows ? 'python' : 'python3')

const LOG = '[rag-evaluate]'

// 自举命令的输出必须走 stderr：本进程的 stdout 是 MCP 的 JSON-RPC 通道，
// 混入任何非协议内容都会破坏握手。
function run(command, args) {
  const result = spawnSync(command, args, { cwd: pkgDir, encoding: 'utf8' })
  if (result.stdout) process.stderr.write(result.stdout)
  if (result.stderr) process.stderr.write(result.stderr)
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`命令退出码 ${result.status}：${command}`)
}

function ensureEnvironment() {
  const hash = createHash('sha256').update(readFileSync(requirementsPath)).digest('hex')
  const upToDate =
    existsSync(pythonBin) &&
    existsSync(stampPath) &&
    readFileSync(stampPath, 'utf8').trim() === hash
  if (upToDate) return

  console.error(`${LOG} 正在准备 Python 环境（首次运行或依赖已变更），可能需要一点时间...`)
  if (!existsSync(pythonBin)) run(bootPython, ['-m', 'venv', venvDir])
  run(pythonBin, [
    '-m', 'pip', 'install',
    '--disable-pip-version-check', '--quiet',
    '-r', requirementsPath
  ])
  writeFileSync(stampPath, hash)
  console.error(`${LOG} Python 环境就绪。`)
}

try {
  ensureEnvironment()
} catch (err) {
  console.error(`${LOG} Python 环境准备失败：${err.message}`)
  console.error(`${LOG} 可用 RAG_EVALUATE_PYTHON 指定解释器，或手动执行：`)
  console.error(`${LOG}   ${bootPython} -m venv "${venvDir}"`)
  console.error(`${LOG}   "${pythonBin}" -m pip install -r "${requirementsPath}"`)
  process.exit(1)
}

const child = spawn(pythonBin, ['server.py'], {
  cwd: join(pkgDir, 'python'),
  stdio: 'inherit',
  env: { ...process.env, PYTHONUNBUFFERED: '1' }
})
child.on('exit', code => process.exit(code ?? 0))
child.on('error', err => {
  console.error(`${LOG} 启动失败：${err.message}`)
  process.exit(1)
})
