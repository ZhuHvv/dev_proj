const SVG_NS = 'http://www.w3.org/2000/svg'
const PALETTE = {
  blue:   { fill: '#eaf3ff', stroke: '#79a6df' },
  purple: { fill: '#f1edff', stroke: '#9a89d5' },
  orange: { fill: '#fff4e5', stroke: '#d69a49' },
  green:  { fill: '#eaf8ef', stroke: '#6fa981' },
  red:    { fill: '#fff0f0', stroke: '#d97a7a' },
  gray:   { fill: '#f8fafc', stroke: '#a9b4c3' }
}

const svg = document.querySelector('svg')

function element (tag, attrs = {}, parent = svg) {
  const node = document.createElementNS(SVG_NS, tag)
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value)
  parent.appendChild(node)
  return node
}

function initDiagram (titleText, descriptionText) {
  const title = element('title', { id: 'diagram-title' })
  title.textContent = titleText
  const desc = element('desc', { id: 'diagram-desc' })
  desc.textContent = descriptionText
  svg.setAttribute('aria-labelledby', 'diagram-title diagram-desc')
  const defs = element('defs')
  defs.innerHTML = `
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#64748b"/></marker>
    <marker id="arrow-soft" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#94a3b8"/></marker>
    <marker id="arrow-purple" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#7c6fbd"/></marker>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#0f172a" flood-opacity="0.07"/></filter>`
}

function textLines (parent, x, y, lines, className, lineHeight = 18, anchor = 'middle') {
  const text = element('text', { x, y, class: className, 'text-anchor': anchor }, parent)
  lines.forEach((line, index) => {
    const tspan = element('tspan', { x, dy: index === 0 ? 0 : lineHeight }, text)
    tspan.textContent = line
  })
  return text
}

function panel ({ x, y, w, h, title, note = '', number = '', color = '#79a6df', fill = '#f8fafc' }) {
  element('rect', { x, y, width: w, height: h, rx: 16, fill })
  let textX = x + 18
  if (number !== '') {
    element('circle', { cx: x + 24, cy: y + 25, r: 14, fill: color })
    const n = element('text', { x: x + 24, y: y + 30, 'text-anchor': 'middle', 'font-size': 13, 'font-weight': 600, fill: '#fff' })
    n.textContent = number
    textX = x + 48
  }
  const heading = element('text', { x: textX, y: y + 30, class: 'panel-title' })
  heading.textContent = title
  if (note) {
    const subtitle = element('text', { x: textX, y: y + 49, class: 'panel-note' })
    subtitle.textContent = note
  }
}

function nodeBox ({ x, y, w, h, kind = 'purple', owner = '', lines = [], sub = '', radius = 10, shadow = true }) {
  const color = PALETTE[kind]
  const group = element('g')
  element('rect', { x, y, width: w, height: h, rx: radius, fill: color.fill, stroke: color.stroke, class: `node${shadow ? ' shadow' : ''}` }, group)
  if (owner) {
    const ownerText = element('text', { x: x + w / 2, y: y + 19, class: 'node-owner' }, group)
    ownerText.textContent = owner
  }
  const lineHeight = 18
  const contentHeight = Math.max(lines.length, 1) * lineHeight
  let startY = y + (h - contentHeight) / 2 + 14
  if (owner) startY += 6
  if (sub) startY -= 6
  textLines(group, x + w / 2, startY, lines, 'node-title', lineHeight)
  if (sub) {
    const subText = element('text', { x: x + w / 2, y: y + h - 12, class: 'node-sub' }, group)
    subText.textContent = sub
  }
  return group
}

function diamond ({ cx, cy, w, h, kind = 'orange', lines = [] }) {
  const color = PALETTE[kind]
  const group = element('g')
  element('polygon', { points: `${cx},${cy - h / 2} ${cx + w / 2},${cy} ${cx},${cy + h / 2} ${cx - w / 2},${cy}`, fill: color.fill, stroke: color.stroke, class: 'node shadow' }, group)
  const startY = cy - ((lines.length - 1) * 9) + 5
  textLines(group, cx, startY, lines, 'node-title', 18)
  return group
}

function edge (d, className = 'edge', markerStart = false) {
  const attrs = { d, class: className }
  if (markerStart) attrs['marker-start'] = className.includes('purple') ? 'url(#arrow-purple)' : 'url(#arrow)'
  return element('path', attrs)
}

function edgeLabel (x, y, label, { pill = false, width = 42 } = {}) {
  if (pill) element('rect', { x: x - width / 2, y: y - 16, width, height: 22, rx: 11, fill: '#fff' })
  const text = element('text', { x, y, class: 'edge-label' })
  text.textContent = label
}

function listCard ({ x, y, w, h, kind = 'purple', title, items }) {
  const color = PALETTE[kind]
  element('rect', { x, y, width: w, height: h, rx: 12, fill: color.fill, stroke: color.stroke, class: 'node shadow' })
  const titleText = element('text', { x: x + 16, y: y + 27, class: 'panel-title' })
  titleText.textContent = title
  items.forEach((item, index) => {
    element('circle', { cx: x + 18, cy: y + 51 + index * 23, r: 3.5, fill: color.stroke })
    const line = element('text', { x: x + 30, y: y + 55 + index * 23, class: 'list-line' })
    line.textContent = item
  })
}
