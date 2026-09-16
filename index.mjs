/**
 * 把本插件自带的 skill 注册进 DSH 的 skill 注册表。
 *
 * 为什么需要这个文件：web profile 会禁用 host 层的 `skill-filesystem`
 * （注释原文：presets own local discovery），真正生效的那一行由 agent preset
 * 挂载且不带配置。因此仅靠在 cordis.patch.yml 里覆盖 `skill-filesystem` 的
 * `customSkillDirs` 无法让插件包内的 skills 目录被发现。
 * 部署级插件直接向注册表注册提供方，则不受该分层影响。
 *
 * @module dsh-rag-evaluate-plugin
 */

import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const PROVIDER_NAME = 'rag-evaluate'

/** 打包型 skill 提供方的标准优先级，等同 @deepseek-ai/dsh-skill 的 BUNDLED_SKILL_RANK。 */
const BUNDLED_SKILL_RANK = 600

const SKILL_URL = new URL('./skills/rag-evaluate/SKILL.md', import.meta.url)
const RESOURCE_BASE = {
  kind: 'directory',
  path: fileURLToPath(new URL('./skills/rag-evaluate/', import.meta.url))
}

const INVOCATION = { modelInvocable: true, userInvocable: true }

/**
 * 解析 SKILL.md 的 YAML frontmatter 与正文。
 * 只支持单行的 `key: value`，本插件的 frontmatter 保持该形式即可，不引入 YAML 依赖。
 */
function parseSkill(markdown) {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(markdown)
  if (match === null) throw new Error('SKILL.md 缺少 frontmatter')

  const fields = {}
  for (const line of match[1].split(/\r?\n/)) {
    const entry = /^([A-Za-z][\w-]*):\s*(.*)$/.exec(line)
    if (entry !== null) fields[entry[1]] = entry[2].trim()
  }
  if (!fields.name || !fields.description) {
    throw new Error('SKILL.md 的 frontmatter 缺少 name 或 description')
  }

  return { fields, content: markdown.slice(match[0].length).trim() }
}

async function loadSkill() {
  // 每次都重新读盘。目录会在每个请求边界刷新，缓存会让 SKILL.md 的编辑
  // 在插件重载前一直不生效，测试时很费解。
  return parseSkill(await readFile(SKILL_URL, 'utf8'))
}

function summary(fields) {
  return {
    name: fields.name,
    description: fields.description,
    ...(fields.whenToUse === undefined ? {} : { whenToUse: fields.whenToUse }),
    invocation: INVOCATION,
    provider: PROVIDER_NAME,
    source: 'bundled',
    resourceBase: RESOURCE_BASE
  }
}

const provider = {
  name: PROVIDER_NAME,

  async list() {
    const { fields } = await loadSkill()
    return [{ ...summary(fields), rank: BUNDLED_SKILL_RANK, locator: fields.name }]
  },

  async get() {
    const { fields, content } = await loadSkill()
    return { ...summary(fields), content }
  }
}

/** Cordis 插件名。 */
const name = 'rag-evaluate-skills'

/** 依赖 skill 注册表服务。 */
const inject = ['skills']

/** 把本插件的 skill 提供方注册到 `ctx.skills`。 */
function apply(ctx) {
  ctx.skills.registerProvider(() => provider)
}

export { apply, inject, name }
