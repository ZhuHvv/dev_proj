"""Rebuild the red/white diagrams and their editable Markdown sources (stdlib only)."""
from pathlib import Path
import html
import json
import math
import re

HERE = Path(__file__).resolve().parent
REVIEW = HERE.parent.parent
RED = '#ef233c'
INK = '#24262b'
MUTED = '#626873'
THEME = {
    'theme': 'base',
    # Native SVG labels avoid foreignObject clipping in Markdown preview hosts.
    'htmlLabels': False,
    # Mermaid's background variable alone does not paint the root SVG canvas.
    'themeCSS': '& { background-color: #ffffff !important; color-scheme: light; } .actor-line { stroke: #969ca6 !important; }',
    'themeVariables': {
        'background': '#ffffff', 'primaryColor': '#fff1f2',
        'primaryTextColor': INK, 'primaryBorderColor': RED,
        'secondaryColor': '#ffffff', 'tertiaryColor': '#fafafa',
        'lineColor': MUTED, 'textColor': INK, 'edgeLabelBackground': '#ffffff',
        'fontFamily': 'Microsoft YaHei, PingFang SC, sans-serif', 'fontSize': '16px',
        'actorBkg': '#ffffff', 'actorBorder': RED, 'actorTextColor': INK,
        'actorLineColor': '#d7d9de', 'signalColor': MUTED, 'signalTextColor': INK,
        'labelBoxBkgColor': '#fff1f2', 'labelBoxBorderColor': '#fecdd3',
        'labelTextColor': INK, 'loopTextColor': INK,
        'noteBkgColor': '#fff1f2', 'noteBorderColor': '#fecdd3', 'noteTextColor': INK,
        'activationBkgColor': '#fff1f2', 'activationBorderColor': RED,
        'sequenceNumberColor': '#ffffff',
    },
    'flowchart': {'curve': 'linear', 'nodeSpacing': 36, 'rankSpacing': 48, 'htmlLabels': False, 'padding': 24},
    'sequence': {'useMaxWidth': True, 'mirrorActors': False, 'wrap': False, 'messageMargin': 48, 'width': 180, 'actorMargin': 60},
}

from diagram_specs import DIAGRAMS

def esc(s): return html.escape(str(s), quote=True)
def mermaid(d):
    init = '%%{init: ' + json.dumps(THEME,ensure_ascii=False) + '}%%\n'
    if d['kind']=='flow':
        lines=['flowchart TB']
        for key,label,sub,col,row,kind in d['nodes']:
            txt=label if kind=='decision' else label+'<br/>'+sub
            shape = '{"'+txt+'"}' if kind=='decision' else '["'+txt+'"]'
            lines.append('    '+key+shape)
        for edge in d['edges']:
            a,b,label,dashed,*_=edge
            op='-.->' if dashed else '-->'
            lines.append(f'    {a} {op}'+(f'|"{label}"|' if label else '')+f' {b}')
        lines += ['    classDef focal fill:#ef233c,color:#ffffff,stroke:#ef233c,stroke-width:2px',
                  '    classDef quiet fill:#ffffff,color:#24262b,stroke:#d3d6dc',
                  '    classDef decision fill:#fff1f2,color:#24262b,stroke:#ef233c',
                  '    classDef store fill:#fafafa,color:#24262b,stroke:#969ca6']
        for key,_,_,_,_,kind in d['nodes']:
            lines.append(f'    class {key} '+{'focus':'focal','decision':'decision','store':'store'}.get(kind,'quiet'))
    else:
        lines=['sequenceDiagram','    autonumber']
        for i,a in enumerate(d['actors']): lines.append(f'    participant A{i} as {a}')
        for i,(a,b,label,kind) in enumerate(d['messages']):
            frag=d.get('fragment')
            if frag and i==frag[0]: lines.append('    opt '+frag[2])
            arrow={'call':'->>','return':'-->>','event':'--)'}[kind]
            lines.append(f'    A{a}{arrow}A{b}: {label}')
            if frag and i==frag[1]: lines.append('    end')
    return init+'\n'.join(lines)+'\n'

def path(points):
    # Round each right-angle bend; never use slanted connector segments.
    p=[tuple(x) for x in points]
    parts=[f'M {p[0][0]} {p[0][1]}']
    for i in range(1,len(p)-1):
        a,b,c=p[i-1],p[i],p[i+1]
        d1=math.dist(a,b);d2=math.dist(b,c)
        if not d1 or not d2: continue
        r=min(8,d1/2,d2/2)
        before=(b[0]+(a[0]-b[0])*r/d1,b[1]+(a[1]-b[1])*r/d1)
        after=(b[0]+(c[0]-b[0])*r/d2,b[1]+(c[1]-b[1])*r/d2)
        parts.append(f'L {before[0]:g} {before[1]:g} Q {b[0]} {b[1]} {after[0]:g} {after[1]:g}')
    parts.append(f'L {p[-1][0]} {p[-1][1]}')
    return ' '.join(parts)

def text(x,y,value,size=20,color=INK,anchor='middle',weight=500):
    return f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{esc(value)}</text>'
def label(x,y,value):
    width=sum(16 if ord(c)>255 else 8 for c in value)+16
    return f'<rect x="{x-width/2}" y="{y-20}" width="{width}" height="28" rx="4" fill="white"/>'+text(x,y,value,16,MUTED)
def connector(points,kind='call'):
    dashed=kind in ('event','return','exception')
    mark='open' if kind=='event' else 'arrow'
    return f'<path d="{path(points)}" fill="none" stroke="{MUTED}" stroke-width="1.6"'+(' stroke-dasharray="6 5"' if dashed else '')+f' marker-end="url(#{mark})"/>'

def svg(d):
    slug=d['slug']; sequence_mode=d['kind']=='sequence'
    width=1280 if sequence_mode else 960
    height=240+len(d['messages'])*72 if sequence_mode else max(n[4] for n in d['nodes'])*144+280
    height=max(height,600)
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="{slug}-title {slug}-desc">',
      f'<title id="{slug}-title">{esc(d["title"])}</title><desc id="{slug}-desc">{esc(d["desc"])}</desc>',
      '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#626873"/></marker>',
      '<marker id="arrow-accent" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#ef233c"/></marker>',
      '<marker id="arrow-link" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#626873"/></marker>',
      '<marker id="open" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="none" stroke="#626873" stroke-width="1.4"/></marker></defs>',
      '<rect width="100%" height="100%" fill="#ffffff"/>',
      '<style>text{font-family:"Microsoft YaHei","PingFang SC",sans-serif}</style>',
      f'<rect x="40" y="32" width="8" height="32" rx="4" fill="{RED}"/>',
      text(64,56,d['title'],28,INK,'start',700)]
    if sequence_mode:
        n=len(d['actors']); xs=[120+i*(1040/(n-1)) for i in range(n)]
        for i,x in enumerate(xs):
            parts += [f'<line x1="{x}" y1="152" x2="{x}" y2="{height-80}" stroke="#d3d6dc" stroke-dasharray="5 7"/>',
              f'<rect x="{x-104}" y="96" width="208" height="56" rx="8" fill="#fff1f2" stroke="#ef233c"/>',text(x,132,d['actors'][i],20,INK)]
        frag=d.get('fragment')
        if frag:
            y=204+frag[0]*72-36
            parts += [f'<rect x="{xs[1]-40}" y="{y}" width="{xs[2]-xs[1]+80}" height="{(frag[1]-frag[0]+1)*72+12}" fill="#fafafa" stroke="#d7d9de"/>',text(xs[1],y+24,'OPT · '+frag[2],16,MUTED,'start')]
        for i,(a,b,msg,kind) in enumerate(d['messages']):
            y=208+i*72; x1=xs[a];x2=xs[b]
            if a==b:
                pts=[(x1,y),(x1+72,y),(x1+72,y+24),(x1,y+24)]
                lx=x1+88; anch='start'
            else:
                pts=[(x1,y),(x2,y)];lx=(x1+x2)/2;anch='middle'
            parts.append(connector(pts,kind))
            if a==b: parts.append(text(lx,y-12,f'{i+1:02d}  '+msg,16,MUTED,anch))
            else: parts.append(label(lx,y-16,f'{i+1:02d}  '+msg))
    else:
        pos={n[0]:(40+n[3]*320,120+n[4]*144,240,88) for n in d['nodes']}
        labels=[]
        for edge in d['edges']:
            a,b,msg,dashed,*extras=edge
            x,y,w,h=pos[a];u,v,ww,hh=pos[b]; ax=x+w/2;bx=u+ww/2
            incoming=sorted([e for e in d['edges'] if e[1]==b and pos[e[0]][1]!=v],key=lambda e:pos[e[0]][0])
            if not extras and len(incoming)>1 and edge in incoming:
                bx += (incoming.index(edge)-(len(incoming)-1)/2)*48
            if extras:
                pts=extras[0]; lx,ly=extras[1] if len(extras)>1 else (pts[0][0],pts[0][1]-16)
            elif x==u:
                mid=(y+h+v)/2
                pts=[(ax,y+h),(ax,mid),(bx,mid),(bx,v)] if ax!=bx else [(ax,y+h),(bx,v)]
                lx=ax-120;ly=mid+4
            elif y==v:
                pts=[(x+w if u>x else x,y+44),(u if u>x else u+ww,v+44)]
                lx=(pts[0][0]+pts[1][0])/2;ly=y+28
            else:
                # From a side port to a top/bottom port, one rounded elbow.
                sx=x+w if u>x else x
                pts=[(sx,y+44),(bx,y+44),(bx,v if v>y else v+hh)]
                lx=(sx+bx)/2;ly=y+28
            parts.append(connector(pts,'exception' if dashed else 'call'))
            if msg: labels.append(label(lx,ly,msg))
        parts += labels
        for key,name,sub,_,_,kind in d['nodes']:
            x,y,w,h=pos[key]; fill='#ffffff';stroke='#d3d6dc';color=INK
            if kind=='focus': fill=RED;stroke=RED;color='white'
            if kind=='store': fill='#fafafa';stroke='#969ca6'
            if kind=='decision':
                # Hexagonal condition box leaves enough space for Chinese labels.
                parts.append(f'<path d="M{x+20} {y} H{x+w-20} L{x+w} {y+h/2} L{x+w-20} {y+h} H{x+20} L{x} {y+h/2} Z" fill="#fff1f2" stroke="{RED}"/>')
            else: parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>')
            # Keep long technical labels readable on their own line.
            size=12
            parts += [text(x+w/2,y+36,name,16,color,'middle',600),text(x+w/2,y+64,sub,size,'#ffffff' if kind=='focus' else MUTED)]
    parts += [f'<line x1="40" y1="{height-56}" x2="{width-40}" y2="{height-56}" stroke="#e5e7eb"/>',
              text(40,height-24,'CAMPUSDASH  /  源码流程 · 红色强调关键处理，非风险等级',16,MUTED,'start'),'</svg>']
    return '\n'.join(parts)

def write_assets():
    for d in DIAGRAMS:
        graphic=svg(d)
        body=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(d['title'])}</title>
<style>body{{margin:0;background:white;color:{INK};font-family:"Microsoft YaHei","PingFang SC",sans-serif}}main{{max-width:1120px;margin:24px auto;padding:0 24px}}svg{{display:block;width:100%;height:auto}}p{{font-size:16px;line-height:1.8;color:{MUTED};margin:16px 40px}}@media print{{main{{margin:0;padding:0}}}}</style></head><body><main>{graphic}<p>{esc(d['desc'])}</p><p>{esc(d['note'])}</p></main></body></html>'''
        (HERE/(d['slug']+'.html')).write_text(body,encoding='utf-8')
        (HERE/(d['slug']+'.mmd')).write_text(mermaid(d),encoding='utf-8')



def update_docs():
    for filename in ('01_project_overview.md', '02_core_call_chain.md'):
        p=REVIEW/filename
        s=p.read_text(encoding='utf-8')
        for d in DIAGRAMS:
            slug=d['slug']
            marker='<!-- diagram:'+slug+' -->'
            if marker not in s:
                continue
            block=marker+'\n\n**'+d['title']+'**\n\n```mermaid\n'+mermaid(d)+'```\n\n[放大预览](assets/diagrams/'+slug+'.html) · '+d['note']+'\n\n<!-- /diagram:'+slug+' -->'
            s=re.sub(r'<!-- diagram:'+slug+r' -->.*?<!-- /diagram:'+slug+r' -->',lambda m:block,s,flags=re.S)
        p.write_text(s,encoding='utf-8')

if __name__=='__main__':
    write_assets()
    update_docs()
    print('Generated',len(DIAGRAMS),'offline HTML previews and Mermaid sources.')
