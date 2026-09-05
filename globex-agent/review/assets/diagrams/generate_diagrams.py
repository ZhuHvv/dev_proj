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

DIAGRAMS = []
def flow(slug, title, desc, nodes, edges, note='实线：处理流程　·　虚线：条件异常或异步事件'):
    # node: id, label, secondary label, column, row, kind; rows/columns are editorial positions.
    d = dict(slug=slug, title=title, desc=desc, kind='flow', nodes=nodes, edges=edges, note=note)
    DIAGRAMS.append(d)
    return slug

def sequence(slug, title, desc, actors, messages, note, fragment=None):
    d = dict(slug=slug, title=title, desc=desc, kind='sequence', actors=actors,
             messages=messages, note=note, fragment=fragment)
    DIAGRAMS.append(d)
    return slug

# Flow connections can supply a custom orthogonal route and off-stroke label position.
# edges: source, target, text, dashed, optional route, optional label x/y.
flow('01-execution', '请求在哪里执行', '先选择 API 直跑或队列 worker，再进入同一个 Orchestrator。', [
 ('ui','React 前端','提交购物诉求',1,0,'input'),
 ('api','FastAPI','POST /commerce/intents',1,1,'normal'),
 ('mode','启用队列？','REDIS_URL + QUEUE_ENABLED',1,2,'decision'),
 ('queue','Redis Stream → worker','入队、领取、执行',2,3,'store'),
 ('o','统一请求编排','MainAgentOrchestrator',1,4,'focus'),
], [('ui','api','',False),('api','mode','',False),('mode','queue','是：队列执行',False),
    ('mode','o','否：API 直跑',False),('queue','o','',False)],
 'API 与 worker 共用编排代码，但分别持有各自的内存状态。')

flow('01-agent-events', '编排、工具与事件出口', '缓存与 Agent 执行汇合到编排收尾，事件由执行进程的总线投递。', [
 ('o','Orchestrator','恢复会话，检查语义缓存',1,0,'normal'),
 ('cache','缓存命中？','满足缓存前置条件后查询',1,1,'decision'),
 ('hit','使用缓存文本','跳过 reply loop',0,2,'normal'),
 ('main','MainAgent 执行','业务工具 / Task / 子 Agent',2,2,'focus'),
 ('finish','编排收尾','审核文本，发布最终事件',1,3,'normal'),
 ('bus','执行进程 EventBus','直跑为 API；队列为 worker',1,4,'store'),
 ('web','API → WebSocket → 前端','本地投递 / Redis Pub/Sub',1,5,'normal'),
], [('o','cache','',False),('cache','hit','是',False),('cache','main','否',False),
    ('hit','finish','',False),('main','finish','',False),('finish','bus','',True),('bus','web','',True)],
 '这里只画正常完成 / 缓存命中；过程事件也经 EventBus，异常分支见正文。')

flow('01-product', '商品检索：召回后再过滤', '主路径从问句向量化到商品卡，硬条件是配送与价格。', [
 ('q','归一化查询','normalized_query',1,0,'input'),
 ('v','向量化 → Qdrant','最多 8 个商品 ID',1,1,'store'),
 ('r','仓储回查 → 可选精排','ProductRepository / reranker',1,2,'normal'),
 ('f','配送与价格硬过滤','ship_to / price_max_major',1,3,'focus'),
 ('c','Top-K 商品卡','ProductCard',1,4,'normal'),
], [('q','v','',False),('v','r','',False),('r','f','',False),('f','c','',False)],
 '库存不参与硬过滤；异常 / 空候选的降级分支见调用链 §4.1。')

flow('01-knowledge', '品类知识：独立检索链', '用户问题通过知识库和独立向量存储取得 Markdown 片段。', [
 ('q','用户问题','question',1,0,'input'),('kb','知识库检索','KnowledgeBase.search',1,1,'focus'),
 ('store','独立向量存储','QdrantStore',1,2,'store'),('chunks','Markdown 知识片段','knowledge/*.md',1,3,'normal'),
], [('q','kb','',False),('kb','store','',False),('store','chunks','',False)],
 '商品向量与知识向量使用不同的 collection 和 embedding 接线。')

sequence('02-direct','API 直跑：事件与返回值分开','正常完成示例：实时事件先投递，HTTP 返回还要等待编排收尾。',
 ['React 前端','FastAPI / EventBus','Orchestrator'],[
 (0,1,'POST /commerce/intents','call'),(1,1,'DTO → SubmitIntentInput','call'),
 (1,2,'handle_intent(intent)','call'),(2,1,'token.delta / final.result','event'),
 (1,0,'WebSocket：更新界面','event'),(2,1,'SubmitIntentOutput（finally 后）','return'),
 (1,0,'HTTP：SubmitIntentResponse','return')],
 '实线：调用　·　虚线：返回或事件；前端当前不解析 HTTP 正文。')

sequence('02-queue-submit','队列：提交与消费','新提交且正常完成的路径；queued、done 与 XACK 是不同写入。',
 ['FastAPI','Redis','worker','Orchestrator'],[
 (0,1,'SET NX 去重键 · 600 秒','call'),(0,1,'XADD IntentTask','call'),
 (0,1,'SET TaskStatus = queued','call'),(2,1,'XREADGROUP 领取新消息','call'),
 (1,2,'IntentTask','return'),(2,1,'SET TaskStatus = running','call'),
 (2,3,'handle_intent(intent)','call'),(3,2,'SubmitIntentOutput（finally 后）','return'),
 (2,1,'SET TaskStatus = done','call'),(2,1,'XACK 消费确认','call')],
 '读取可与 queued 写入交错；图中为一种正常时序，跨进程事件见下一图。')

sequence('02-queue-result','队列：实时事件与状态兜底','worker 通过 Redis 背板送事件；API 无事件时按 task ID 查询结果。',
 ['worker EventBus','Redis','FastAPI / EventBus','React 前端'],[
 (0,1,'Pub/Sub 广播：过程 / final.result','event'),
 (1,2,'订阅收到事件 → deliver_local','event'),(2,3,'WebSocket：显示结果','event'),
 (2,1,'按 task_id 查询 TaskStatus','call'),(1,2,'done / failed / 其他状态','return'),
 (2,3,'HTTP：结果或等待超时文本','return')],
 '状态兜底在等待期间发生，不要求 worker 先完成；HTTP 正文当前不用于聊天渲染。',
 (3,4,'连续 2 秒没有任何 session 事件时'))

flow('02-session','会话恢复：命中内存即复用','仅首次在本进程访问该 session 时，才读取持久化状态并创建 Agent。',[
 ('start','get_or_create','按 shopping_session_id 查找',1,0,'input'),
 ('cache','进程内有 Agent？','SessionRegistry._agents',1,1,'decision'),
 ('reuse','直接返回已有 Agent','不重新读取 Store',0,2,'focus'),
 ('load','读取并解析状态','SessionStore.load',1,2,'store'),
 ('valid','可恢复？','存在且通过 AgentState 校验',1,3,'decision'),
 ('state','使用已恢复状态','restored_state',0,4,'normal'),
 ('fresh','使用新状态','restored_state = None',2,4,'normal'),
 ('build','构建、缓存并返回','MainAgentFactory.build',1,5,'normal'),
], [('start','cache','',False),('cache','reuse','是',False),('cache','load','否',False),
 ('load','valid','',False),('valid','state','是',False),('valid','fresh','否',False),
 ('state','build','',False),('fresh','build','',False)],
 '无数据、读取失败或解析失败走新状态；命中内存不发生再次写入 _agents。')

flow('02-product','商品检索：正常路径与降级', '工具先经过韧性中间件，再转换参数；关键词降级发生在硬过滤之前。',[
 ('tool','Agent → 韧性中间件','ToolResilienceMiddleware',1,0,'input'),
 ('args','商品工具：转换参数','ProductSearchSpec',1,1,'normal'),
 ('v','向量候选非空？','embed → Qdrant → 仓储回查',1,2,'decision'),
 ('key','关键词召回','keyword_2gram',0,3,'normal'),
 ('rank','尝试可选精排','成功：精排分；否则：向量分',2,3,'normal'),
 ('filter','配送 / 价格过滤 → Top-K','不按库存过滤',1,4,'focus'),
 ('out','组装商品卡并返回','tool.result + ToolChunk JSON',1,5,'normal'),
], [('tool','args','',False),('args','v','',False),('v','key','否 / 捕获异常',False),
 ('v','rank','是',False),('key','filter','',False),('rank','filter','',False),('filter','out','',False)],
 '外层超时不保证完成降级；过滤后零命中不会重新召回。')

flow('02-knowledge','品类知识：工具到观察结果','知识工具把检索片段转换为 insights，作为模型后续回答的依据。',[
 ('a','MainAgent / SearchAgent','选择 category_insight_tool',1,0,'input'),
 ('t','知识工具','question / top_k',1,1,'normal'),
 ('kb','KnowledgeBase.search','独立 QdrantStore',1,2,'focus'),
 ('i','组织 insights','content / source / score',1,3,'normal'),
 ('o','返回模型观察','ToolChunk JSON',1,4,'normal'),
], [('a','t','',False),('t','kb','',False),('kb','i','',False),('i','o','',False)],
 '外层仍有工具超时与熔断；此图展开知识检索本体，不包含替代 RAG 降级链。')

sequence('02-dispatch','子 Agent：返回文本，旁路发布事件','派发创建独立 AgentState；事件进入 EventBus，不是直接返回给 MainAgent。',
 ['MainAgent','task_dispatch','子 Agent','业务工具','EventBus'],[
 (0,1,'subagent_type + demands','call'),(1,4,'agent.dispatch','event'),
 (1,1,'Factory.build：独立 AgentState','call'),(1,1,'SearchAgent 可选注入偏好','call'),
 (1,2,'reply(inputs)','call'),(2,3,'搜索 / 订单工具','call'),
 (3,4,'tool.invoke / tool.result','event'),(3,2,'ToolChunk','return'),
 (2,1,'最终文本','return'),(1,4,'task_dispatch tool.result：耗时','event'),
 (1,0,'ToolChunk：子 Agent 最终文本','return')],
 '可选偏好步骤由 PREFERENCE_SUBAGENT_INJECT 等条件控制；子 Agent 不继承主历史。')

flow('02-order','下单：正常处理与回补边界','将普通异常回补与 save 失败分开，避免把所有失败都画成自动回滚。',[
 ('t','订单工具：转换参数','buyer / items / address',1,0,'input'),
 ('items','items 非空？','PlaceOrderUseCase',1,1,'decision'),
 ('work','查商品 → 扣库存 → 建订单','OrderLine / next_order_id / place',1,2,'focus'),
 ('rb','尝试回补 deducted','仅 try 内普通 Exception',2,2,'normal'),
 ('save','保存订单','OrderRepository.save',1,3,'store'),
 ('done','返回订单快照','Order.snapshot',1,4,'normal'),
 ('err','异常向外传播','转工具 ERROR 或继续抛出',0,4,'normal'),
], [('t','items','',False),('items','work','是',False),
 ('items','err','否：try 外',False),
 ('work','save','',False),('work','rb','普通异常',True),
 ('rb','err','回补后抛出',True,[(800,496),(800,840),(160,840),(160,784)],(520,824)),
 ('save','done','',False),('save','err','失败：不回补',True,[(360,596),(304,596),(304,740),(280,740)],(232,580))],
 'CancelledError 不进回补 except；负数量还可能令回补失败。库存与订单不在统一事务。')

flow('02-retry','两层重试：建流与整段消费','模型包装器处理建流前瞬时错误；外层还处理流消费时逃出的瞬时错误。',[
 ('model','模型调用与建流','含模型层重试及可选备用',1,0,'focus'),
 ('stream','消费 reply_stream','工具执行 / 文本事件',1,1,'normal'),
 ('ok','流耗尽：继续收尾','返回当前 final_text',1,2,'normal'),
 ('err','异常逃出','建流失败或消费失败',2,1,'normal'),
 ('test','瞬时错误且可重试？','Orchestrator 最多重进 2 次',2,2,'decision'),
 ('retry','保留状态，inputs = []','退避后重新进入 reply loop',2,3,'normal'),
 ('fail','发布 error，返回 [error]','该异常分支不发 final.result',0,3,'normal'),
], [('model','stream','建流成功',False),('stream','ok','未抛异常',False),
 ('model','err','建流失败',True),('stream','err','消费失败',True),('err','test','',False),
 ('test','retry','是',False),('test','fail','否',False,[(680,452),(648,452),(648,596),(280,596)],(536,580)),
 ('retry','model','重新尝试',True,[(800,640),(936,640),(936,88),(480,88),(480,120)],(760,72))],
 '模型层仅重试建流前瞬时错误：最多 LLM_MAX_RETRIES + 1 次；不回滚工具副作用。')

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
    if slug=='02-order': height=920
    if slug=='02-retry': height=800
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
              text(40,height-24,'GLOBEX  /  源码流程 · 红色强调关键处理，非风险等级',16,MUTED,'start'),'</svg>']
    return '\n'.join(parts)

def write_assets():
    for d in DIAGRAMS:
        graphic=svg(d)
        body=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(d['title'])}</title>
<style>body{{margin:0;background:white;color:{INK};font-family:"Microsoft YaHei","PingFang SC",sans-serif}}main{{max-width:1120px;margin:24px auto;padding:0 24px}}svg{{display:block;width:100%;height:auto}}p{{font-size:16px;line-height:1.8;color:{MUTED};margin:16px 40px}}@media print{{main{{margin:0;padding:0}}}}</style></head><body><main>{graphic}<p>{esc(d['desc'])}</p><p>{esc(d['note'])}</p></main></body></html>'''
        (HERE/(d['slug']+'.html')).write_text(body,encoding='utf-8')
        (HERE/(d['slug']+'.mmd')).write_text(mermaid(d),encoding='utf-8')

GROUPS = {
 '01_project_overview.md':[['01-execution','01-agent-events'],['01-product'],['01-knowledge']],
 '02_core_call_chain.md':[['02-direct'],['02-queue-submit','02-queue-result'],['02-session'],['02-product'],['02-knowledge'],['02-dispatch'],['02-order'],['02-retry']],
}

def update_docs():
    byid={d['slug']:d for d in DIAGRAMS}
    for filename,groups in GROUPS.items():
        p=REVIEW/filename; s=p.read_text(encoding='utf-8')
        def block(slug):
            d=byid[slug]
            return f'<!-- diagram:{slug} -->\n\n**{d["title"]}**\n\n```mermaid\n{mermaid(d)}```\n\n[放大预览](assets/diagrams/{slug}.html) · {d["note"]}\n\n<!-- /diagram:{slug} -->'
        if '<!-- diagram:' in s:
            for group in groups:
                for slug in group:
                    s=re.sub(r'<!-- diagram:'+slug+r' -->.*?<!-- /diagram:'+slug+r' -->',lambda m:block(slug),s,flags=re.S)
        else:
            matches=list(re.finditer(r'```mermaid\n.*?```',s,re.S))
            assert len(matches)==len(groups),(filename,len(matches))
            for m,group in reversed(list(zip(matches,groups))):
                s=s[:m.start()]+'\n\n'.join(block(slug) for slug in group)+s[m.end():]
            s=s.replace('图中实线表示请求或同步处理，虚线表示跨进程异步事件。语义缓存命中与 MainAgent 执行是互斥分支。','两图分别展开执行位置与编排出口；共享 Orchestrator 表示同一套代码，不表示 API 和 worker 共享内存实例。')
        p.write_text(s,encoding='utf-8')

if __name__=='__main__':
    write_assets()
    update_docs()
    print('generated',len(DIAGRAMS),'HTML previews and editable Mermaid sources')
