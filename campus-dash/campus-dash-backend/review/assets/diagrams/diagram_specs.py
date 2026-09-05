"""CampusDash diagrams. One source feeds Markdown Mermaid and offline HTML previews.

Style follows the user-selected Globex documents: white/red, Chinese sans-serif.
Canvas: fit; flows use 960px width, sequences 1280px. No external assets.
"""
DIAGRAMS = []

def flow(slug, title, desc, nodes, edges, note):
    DIAGRAMS.append(dict(slug=slug, title=title, desc=desc, kind='flow', nodes=nodes, edges=edges, note=note))

def sequence(slug, title, desc, actors, messages, note):
    DIAGRAMS.append(dict(slug=slug, title=title, desc=desc, kind='sequence', actors=actors, messages=messages, note=note))

flow('01-runtime', '两个进程，共用业务代码', '在线请求和后台触发分别进入各自进程的应用用例，通过适配器访问共享存储。', [
 ('ui','浏览器','HTTP / WebSocket',0,0,'input'),
 ('trigger','消息与定时调度','MQ / @Scheduled',2,0,'input'),
 ('app','在线进程','dash-bootstrap + presentation',0,1,'normal'),
 ('worker','后台进程','dash-worker',2,1,'normal'),
 ('uc','相同用例代码，各自实例','dash-application',1,2,'focus'),
 ('infra','领域端口 → 适配器','dash-infrastructure',1,3,'normal'),
 ('store','业务事实与外部状态','MySQL / Redis / RocketMQ',1,4,'store'),
], [('ui','app','',False),('trigger','worker','',False),('app','uc','',False),('worker','uc','',False),('uc','infra','',False),('infra','store','',False)],
 '箭头表示处理入口与访问方向；共用代码不等于共享内存或连接。')

flow('01-lifecycle', '正常履约：从发布到结算', '六个业务节点展示正常成功路径，取消、争议和超时分支在正文分别展开。', [
 ('p','发布并托管','PUBLISHED / HELD',1,0,'normal'),
 ('g','抢中待确认','LOCKED',1,1,'normal'),
 ('a','跑腿确认','ACCEPTED',1,2,'normal'),
 ('k','完成取货','PICKED_UP',1,3,'normal'),
 ('d','送达并登记后续消息','DELIVERED',1,4,'focus'),
 ('s','人工或自动结算','SETTLED / RELEASED',1,5,'normal'),
], [('p','g','',False),('g','a','',False),('a','k','',False),('k','d','',False),('d','s','',False)],
 '此图只表达成功主线；取消、争议、候选流转见 §4，CLOSED 尚无用例入口。')

flow('01-messages', '两种消息机制，对应两类工作', '定时业务先记录待发事实，资金事件通过半消息包裹本地资金工作；缓存双删另走直接发送。', [
 ('delay','确认超时 / 自动结算','需要到期触发',0,0,'input'),
 ('fund','结算 / 退款 / 仲裁','资金结果通知',2,0,'input'),
 ('local','本地消息表','PENDING → SENT / DEAD',0,1,'store'),
 ('half','MQ 半消息与本地工作','成功后提交消息',2,1,'focus'),
 ('dworker','到期消费 → 业务用例','另有数据库扫描兜底',0,2,'normal'),
 ('fworker','通知落库 / 实时推送','两个消费组',2,2,'normal'),
], [('delay','local','登记',False),('local','dworker','定时发送',True),('fund','half','',False),('half','fworker','提交后可见',True)],
 '虚线表示异步投递；本地消息表仅记录待发事实，不是已完成业务的证明。')

sequence('02-entry','认证成功请求：身份进入用例','展示受保护接口的正常请求骨架，排除路径和拒绝响应在正文说明。',
 ['浏览器','认证拦截器','Controller','应用用例'],[
 (0,1,'HTTP /api/** + Bearer token','call'),
 (1,2,'校验成功：写入 userId','call'),
 (2,3,'CurrentUser → 命令或查询','call'),
 (3,2,'业务结果','return'),
 (2,0,'Result JSON','return')],
 '实线为调用，虚线为返回；未认证返回401，不进入该正常路径。')

sequence('02-publish','发布：外部写入仍在提交之前','发布用例先完成数据库写入，再初始化 Redis，最后才结束数据库事务。',
 ['发布用例','MySQL 事务','Redis'],[
 (0,1,'条件扣款、复式流水、HELD托管','call'),
 (0,1,'DRAFT → PUBLISHED、状态日志','call'),
 (0,2,'初始化slot、登记Bloom','call'),
 (2,0,'调用返回','return'),
 (0,1,'代理提交数据库事务','call'),
 (1,0,'DB提交成功','return')],
 '图为成功路径；Redis不参加DB事务，已写的key不会因DB回滚自动撤销。')

flow('02-grab','抢单：占位后还要数据库裁决','先限流与资格检查，再占用 Redis 名额，数据库成功后执行后置步骤。',[
 ('http','抢单请求','id / runner / requestId',1,0,'input'),
 ('qual','限流与资格通过？','信用分、在途快照',1,1,'decision'),
 ('reject','返回业务失败','不占名额',0,1,'normal'),
 ('lua','Lua 名额裁决','请求去重、扣减、用户集合',1,2,'normal'),
 ('queue','SLOT_FULL → 候选队列','按时间与信用排序',2,2,'store'),
 ('db','MySQL 事务裁决','CAS + 抢单记录 + 日志',1,3,'focus'),
 ('rb','失败后尝试补偿','rollback_slot.lua',2,3,'normal'),
 ('done','超时登记、缓存与推送','DB已提交后继续处理',1,4,'normal'),
], [('http','qual','',False),('qual','reject','否',False),('qual','lua','是',False),('lua','queue','满额',False),('lua','db','占位成功',False),('db','rb','失败',False),('db','done','成功',False)],
 '仅展示主分支；请求重放、不可抢、重复用户和后置异常见 §4 正文。')

flow('02-timeout','超时：校验后换人或重新开放','MQ和扫描共用同一处理用例，状态与round过滤失效触发，数据库事务决定是否应用。',[
 ('in','MQ / DB扫描','errandId + expectedRound',1,0,'input'),
 ('valid','任务存在且状态轮次匹配？','LOCKED + round',1,1,'decision'),
 ('skip','SKIPPED','不修改任务',2,1,'normal'),
 ('choose','未达上限且有候选？','累计round / pollBest',1,2,'decision'),
 ('transfer','换人事务','新grabber、日志、下一轮消息',0,3,'focus'),
 ('revert','回退事务','PUBLISHED、清grabber、日志',2,3,'normal'),
 ('send','事务后dispatch','发送下一轮消息',0,4,'normal'),
 ('post','事务后尝试归还名额','信用事件、缓存失效',2,4,'normal'),
], [('in','valid','',False),('valid','skip','不符',False),('valid','choose','匹配',False),('choose','transfer','是',False),('choose','revert','否',False),('transfer','send','',False),('revert','post','',False)],
 '归还步骤是一次尝试；换人后的Redis身份不匹配等隐患见同节正文。')

sequence('02-settle','结算成功：数据库与消息分别提交','资金适配器先发半消息，再执行本地事务回调，成功后提交消息；false分支见正文。',
 ['结算用例','资金适配器','RocketMQ','MySQL'],[
 (0,1,'资金事件 + LocalWork回调','call'),
 (1,2,'发送半消息','call'),
 (2,1,'发送成功','return'),
 (1,3,'执行回调：托管、任务、分账、信用','call'),
 (3,1,'本地事务提交，回调true','return'),
 (1,2,'commit事务消息','call'),
 (1,0,'返回true，继续后置动作','return')],
 '此图为成功路径；回调false可留下已提交的部分DB更新，不能画成DB自动回滚。')

sequence('02-refund','退款：任务状态先于资金事务','取消或仲裁退款先写任务状态与日志，再通过资金适配器执行退款事务。',
 ['退款用例','MySQL','资金适配器'],[
 (0,1,'CAS任务终态、写状态日志','call'),
 (1,0,'独立写入已完成','return'),
 (0,2,'半消息 + 退款工作回调','call'),
 (2,1,'退款事务：托管、账户、流水','call'),
 (1,2,'资金事务提交成功','return'),
 (2,0,'完成消息提交，返回结果','return')],
 '前两步不在资金事务中；后续失败不会自动恢复任务状态或再次退款。')

flow('02-cache','详情：缓存判空，数据库组装响应','Controller先调用缓存用例做存在性判断，存在时另读数据库组装带动作的卡片。',[
 ('c','Controller.detail','当前viewer + errandId',1,0,'input'),
 ('cache','detailJson：缓存用例','分片 / 逻辑过期 / Bloom / 回源',1,1,'normal'),
 ('empty','结果为空？','Optional JSON',1,2,'decision'),
 ('nf','ERRAND_NOT_FOUND','业务失败',2,3,'normal'),
 ('db','再次读取数据库','ErrandRepository.findById',0,3,'focus'),
 ('card','toCard + availableActions','按viewer计算动作并返回',0,4,'normal'),
], [('c','cache','',False),('cache','empty','',False),('empty','nf','是',False),('empty','db','否',False),('db','card','存在',False)],
 '缓存命中仍有这次DB读取；第二次查无任务也返回NOT_FOUND，算法分支见正文。')

sequence('02-fund','事务回查：以流水存在为提交依据','消息服务器通过checker询问本地事务结果；图展示找到流水的分支。',
 ['RocketMQ Broker','TransactionChecker','MySQL流水表'],[
 (0,1,'请求检查：消息bizNo','call'),
 (1,2,'ledgerExists(bizNo)','call'),
 (2,1,'存在对应流水','return'),
 (1,0,'COMMIT','return')],
 '无流水且年龄≤60秒返回UNKNOWN，超过60秒返回ROLLBACK；回查不校验事件金额。')
