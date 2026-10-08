'use strict';
const $ = (id) => document.getElementById(id);
const icons = {choice:'i-route', boolean:'i-shield', score:'i-bars'};
const types = {choice:'Choice', boolean:'Boolean', score:'Score'};
const templates = {
  route:{name:'工单智能分流', short:'工单分流', kind:'choice', question:'这条客户工单应该交给哪个团队处理？不属于任何团队或资料不足时，选择“其他 / 信息不足”。', options:['账号与登录','支付与订单','设备故障','其他 / 信息不足'], state:'客户反馈：我在登录时一直收不到短信验证码，已经等了十分钟，重试三次仍然不行。我的订单昨天已经支付成功，希望能尽快恢复账号登录。'},
  claim:{name:'文案承诺检查', short:'文案检查', kind:'boolean', question:'这段文案是否包含无法保证的效果承诺或绝对化表述？判断其文字是否作出无条件的结果保证，资料不足时请标记待复核。', options:[], state:'我们的 AI 学习助手，保证所有使用者在 7 天内掌握英语口语，学习效果 100% 有效。每天只需使用 10 分钟，即可实现流利沟通。'},
  value:{name:'内容价值评分', short:'内容评分', kind:'score', question:'按信息量与实用性给材料打 1~5 分：1=空泛宣传；2=只有零散观点；3=主题明确但缺少细节；4=含具体事实、场景或可用建议；5=有可核查的新事实和清楚的行动方法。不把篇幅长当作价值高。', options:[], state:'我们测试了 50 条客服工单的分流效果：系统将 39 条准确分到对应团队，7 条因信息不足交给人工，4 条被分错。错分主要发生在“支付成功但无法登录”的复合问题上。建议先按用户当前诉求分流，再保留另一类问题的标签。'}
};
let kind='choice', activeTemplate='route', currentResult=null, currentRequest=null;
let judging=false, chatting=false, aborter=null, trace=[], toastTimer, view='judge';
let sessionId=crypto.randomUUID();
let history=[];
try { history=JSON.parse(localStorage.getItem('judge-history-v1')||'[]'); if(!Array.isArray(history)) history=[]; history=history.filter(x=>x.result?.decision&&x.request).slice(0,12); } catch { history=[]; }
function icon(id){ const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');const use=document.createElementNS(svg.namespaceURI,'use');use.setAttribute('href','#'+id);svg.append(use);return svg; }
function node(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function showToast(text){$('toast').textContent=text;$('toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),3500);}
function countChars(){$('char-count').textContent=$('state').value.length.toLocaleString()+' / 12,000';}
function invalidateResult(){if(judging)return;currentResult=null;currentRequest=null;$('filled-result').classList.add('hidden');$('loading-result').classList.add('hidden');$('empty-result').classList.remove('hidden');$('export-result').disabled=true;$('result-state').textContent='等待输入';$('result-state').className='result-state';}
function setKind(next){kind=next;document.querySelectorAll('[data-kind]').forEach(b=>b.classList.toggle('selected',b.dataset.kind===kind));$('options-field').classList.toggle('hidden',kind!=='choice');}
function selectTemplate(key){if(judging)return;invalidateResult();activeTemplate=key;const t=templates[key];setKind(t.kind);$('question').value=t.question;$('state').value=t.state;$('options').value=t.options.join('\n');$('template-label').textContent=t.short;document.querySelectorAll('[data-template]').forEach(b=>b.classList.toggle('active',b.dataset.template===key));countChars();}
function selectView(next){view=next;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===next));$('judge-view').classList.toggle('hidden',next!=='judge');$('repair-view').classList.toggle('hidden',next!=='repair');$('crumb').textContent=next==='judge'?'判断工作台':'ATM 报修助手';if($('mobile-switch'))$('mobile-switch').textContent=next==='judge'?'报修助手':'快速判断';location.hash=next;}
function addTrace(event,data){trace.push({event,data});trace=trace.slice(-80);const holder=$('trace-events');holder.replaceChildren();trace.forEach(item=>{const row=node('div',undefined,'trace-event');row.append(node('b',item.event),node('pre',typeof item.data==='string'?item.data:JSON.stringify(item.data,null,2)));holder.append(row);});}
async function streamRequest(path,payload,onEvent,signal){
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal});
  if(!response.ok){let data;try{data=await response.json();}catch{data={error:'服务暂时不可用'};}throw new Error(data.error||'请求失败');}
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',finished=false;
  function parse(chunk){let event='message',data='';for(const line of chunk.split('\n')){if(line.startsWith('event:'))event=line.slice(6).trim();if(line.startsWith('data:'))data+=line.slice(5).trim();}if(!data)return;const parsed=JSON.parse(data);addTrace(event,parsed);if(event==='error')throw new Error(parsed.message);if(event==='result')finished=true;onEvent(event,parsed);}
  try{while(true){const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done}).replace(/\r\n/g,'\n');let split;while((split=buffer.indexOf('\n\n'))>=0){parse(buffer.slice(0,split));buffer=buffer.slice(split+2);}if(done)break;}if(buffer.trim())parse(buffer);if(!finished)throw new Error('连接提前结束，结果尚未确认。');}finally{reader.releaseLock();}
}
function answerValue(result){const d=result.decision;if(d.needs_review&&d[result.kind]===null)return '信息不足';if(result.kind==='choice')return d.choice||'信息不足';if(result.kind==='boolean')return d.boolean===null?'信息不足':d.boolean?'是，条件成立':'否，条件不成立';return d.score===null?'信息不足':d.score+' / 5';}
function renderResult(result,request){
  currentResult=result;currentRequest=request;$('empty-result').classList.add('hidden');$('loading-result').classList.add('hidden');$('filled-result').classList.remove('hidden');$('export-result').disabled=false;
  $('result-state').textContent=result.decision.needs_review?'建议复核':'判断完成';$('result-state').className='result-state '+(result.decision.needs_review?'error':'success');
  $('answer-kind').textContent={choice:'分类结果',boolean:'条件检查',score:'等级评分'}[result.kind];$('answer-value').textContent=answerValue(result);$('answer-reason').textContent=result.decision.reason;
  const options=$('answer-options');options.replaceChildren();options.classList.toggle('score-levels',result.kind==='score');
  if(result.kind==='choice'){request.options.forEach(value=>options.append(node('span',value,value===result.decision.choice?'selected':'')));}
  if(result.kind==='score'){for(let i=1;i<=5;i++){const bar=node('span','',i<=result.decision.score?'selected':'');bar.title='等级 '+i;options.append(bar);}}
  const ms=result.end_to_end_ms??result.inference_ms;$('result-latency').textContent=Number.isFinite(ms)?(ms/1000).toFixed(2)+'s':'—';$('result-type').textContent=types[result.kind];$('result-tokens').textContent=result.total_tokens.toLocaleString();
  const quotes=$('evidence-quotes');quotes.replaceChildren();if(result.decision.evidence.length){result.decision.evidence.forEach(q=>quotes.append(node('blockquote',q)));}else quotes.append(node('p','未找到可直接引用的原文片段，请结合完整材料核查。'));
  $('review-note').classList.toggle('hidden',!result.decision.needs_review);$('result-json').textContent=JSON.stringify(result,null,2);
}
function renderHistory(){
  $('history-count').textContent=history.length;$('nav-count').textContent=history.length;const rows=$('history-rows');rows.replaceChildren();
  if(!history.length){rows.append(node('div','还没有运行记录。试试上面的示例，开始你的第一次判断。','history-empty'));return;}
  history.forEach(item=>{const row=node('button',undefined,'history-row'),label=node('span');label.append(icon(icons[item.result.kind]),document.createTextNode(item.name));const time=new Date(item.at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});row.append(label,node('span',answerValue(item.result)),node('span',((item.result.end_to_end_ms??item.result.inference_ms)/1000).toFixed(2)+'s'),node('span',time));row.addEventListener('click',()=>{if(judging)return;setKind(item.request.kind);$('state').value=item.request.state;$('question').value=item.request.question;$('options').value=item.request.options.join('\n');$('template-label').textContent='历史判断';activeTemplate=null;document.querySelectorAll('[data-template]').forEach(b=>b.classList.remove('active'));countChars();renderResult(item.result,item.request);$('result-state').textContent='历史记录';document.querySelector('.workbench').scrollIntoView({behavior:'smooth',block:'start'});});rows.append(row);});
}
async function runJudge(){
  if(judging)return;const request={kind,state:$('state').value.trim(),question:$('question').value.trim(),options:kind==='choice'?$('options').value.split('\n').map(x=>x.trim()).filter(Boolean):[]};
  if(!request.state||!request.question){showToast('请填写判断问题和材料。');return;}if(kind==='choice'&&request.options.length<2){showToast('请至少设置两个候选答案。');return;}
  judging=true;aborter=new AbortController();currentResult=null;$('export-result').disabled=true;trace=[];
  $('filled-result').classList.add('hidden');$('empty-result').classList.add('hidden');$('loading-result').classList.remove('hidden');$('result-state').textContent='正在判断';$('result-state').className='result-state';$('loading-title').textContent='正在连接判断工具';$('judge-progress').style.width='0%';$('cancel-run').classList.remove('hidden');
  const controls=[...document.querySelectorAll('[data-template],[data-kind]'),$('state'),$('question'),$('options'),$('run-judge')];controls.forEach(b=>b.disabled=true);const started=performance.now();const timer=setInterval(()=>$('loading-time').textContent=((performance.now()-started)/1000).toFixed(1)+'s',100);
  try{await streamRequest('/api/judge',request,(event,data)=>{if(event==='progress'){$('loading-title').textContent=data.message;$('judge-progress').style.width=(data.progress/data.total*100)+'%';}if(event==='result'){renderResult(data,request);history.unshift({name:activeTemplate?templates[activeTemplate].name:'自定义判断',at:new Date().toISOString(),result:data,request});history=history.slice(0,12);try{localStorage.setItem('judge-history-v1',JSON.stringify(history));}catch{showToast('判断已完成，浏览器空间不足，记录未保存。');}renderHistory();}},aborter.signal);
  }catch(error){$('loading-result').classList.add('hidden');$('empty-result').classList.remove('hidden');$('result-state').textContent=error.name==='AbortError'?'已停止等待':'运行失败';$('result-state').className='result-state error';const message=error.name==='AbortError'?'已停止等待这次判断。':error.message;showToast(message.slice(0,160));addTrace('error',{message});}
  finally{judging=false;clearInterval(timer);controls.forEach(b=>b.disabled=false);$('cancel-run').classList.add('hidden');aborter=null;}
}
function chatBubble(text,role){const holder=$('chat-messages');if(holder.querySelector('.chat-welcome'))holder.replaceChildren();holder.append(node('div',role==='user'?'你':'报修助手','chat-role '+role));const bubble=node('div',text.replace(/\*\*(.*?)\*\*/g,'$1'),'chat-bubble '+role);holder.append(bubble);holder.scrollTop=holder.scrollHeight;return bubble;}
function resetTicket(){$('ticket-status').textContent='等待报修';$('ticket-id').textContent='工单创建后，编号会显示在这里。';document.querySelectorAll('#ticket-stages li').forEach((li,i)=>{li.classList.remove('done');li.firstElementChild.textContent=i+1;});}
async function sendChat(text){
  if(chatting||!text.trim())return;chatting=true;$('chat-send').disabled=true;$('reset-chat').disabled=true;$('chat-input').value='';chatBubble(text,'user');const waiting=chatBubble('正在理解你的问题…','assistant waiting');trace=[];
  try{await streamRequest('/api/chat',{message:text,session_id:sessionId,debug:true},(event,data)=>{if(event==='progress'){waiting.textContent='工单处理中：'+data.message;const stages=['已受理','运维人员派单','现场检修','维修完成'];$('ticket-status').textContent=stages[Math.min(3,data.progress-1)]+'（模拟）';$('ticket-id').textContent=(data.message||'').split('|')[0].trim();document.querySelectorAll('#ticket-stages li').forEach((li,i)=>{li.classList.toggle('done',i<data.progress);li.firstElementChild.textContent=i<data.progress?'✓':i+1;});}if(event==='result'){waiting.classList.remove('waiting');waiting.textContent=data.reply.replace(/\*\*(.*?)\*\*/g,'$1');$('chat-messages').scrollTop=$('chat-messages').scrollHeight;if(data.mcp_calls===0&&$('ticket-status').textContent==='等待报修')$('ticket-id').textContent='本次对话未创建工单。';}});
  }catch(error){waiting.classList.remove('waiting');waiting.textContent='请求未完成：'+error.message+'\n若已有工单进度，结果尚未确认，请勿重复报修。';addTrace('error',{message:error.message});}
  finally{chatting=false;$('chat-send').disabled=false;$('reset-chat').disabled=false;}
}
document.querySelectorAll('[data-template]').forEach(b=>b.addEventListener('click',()=>selectTemplate(b.dataset.template)));
document.querySelectorAll('[data-kind]').forEach(b=>b.addEventListener('click',()=>{if(judging)return;invalidateResult();setKind(b.dataset.kind);activeTemplate=null;$('template-label').textContent='自定义判断';document.querySelectorAll('[data-template]').forEach(t=>t.classList.remove('active'));$('question').value=kind==='choice'?templates.route.question:kind==='boolean'?'根据给定材料，指定条件是否成立？请在这里写明你要检查的具体条件。':templates.value.question;}));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>selectView(b.dataset.view)));
document.querySelectorAll('[data-message]').forEach(b=>b.addEventListener('click',()=>sendChat(b.dataset.message)));
$('state').addEventListener('input',()=>{countChars();invalidateResult();});$('question').addEventListener('input',invalidateResult);$('options').addEventListener('input',invalidateResult);$('run-judge').addEventListener('click',runJudge);$('cancel-run').addEventListener('click',()=>aborter?.abort());
$('history-nav').addEventListener('click',()=>{selectView('judge');$('history-section').scrollIntoView({behavior:'smooth'});});
$('clear-history').addEventListener('click',()=>{history=[];localStorage.removeItem('judge-history-v1');renderHistory();showToast('已清空当前浏览器的判断记录。');});
$('copy-answer').addEventListener('click',async()=>{if(!currentResult)return;try{await navigator.clipboard.writeText(JSON.stringify(currentResult,null,2));showToast('结构化结果已复制。');}catch{showToast('无法访问剪贴板，可展开 JSON 手动复制。');}});
$('export-result').addEventListener('click',()=>{if(!currentResult)return;const blob=new Blob([JSON.stringify({request:currentRequest,result:currentResult},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='judge-result-'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
function toggleTrace(open){$('trace-drawer').classList.toggle('hidden',!open);$('trace-backdrop').classList.toggle('hidden',!open);}
$('trace-open').addEventListener('click',()=>toggleTrace(true));$('trace-close').addEventListener('click',()=>toggleTrace(false));$('trace-backdrop').addEventListener('click',()=>toggleTrace(false));
$('chat-form').addEventListener('submit',e=>{e.preventDefault();sendChat($('chat-input').value.trim());});
$('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendChat($('chat-input').value.trim());}});
const originalWelcome=$('chat-messages').firstElementChild.cloneNode(true);
$('reset-chat').addEventListener('click',()=>{if(chatting)return;sessionId=crypto.randomUUID();$('chat-messages').replaceChildren(originalWelcome.cloneNode(true));$('chat-messages').querySelectorAll('[data-message]').forEach(b=>b.addEventListener('click',()=>sendChat(b.dataset.message)));resetTicket();trace=[];$('trace-events').replaceChildren(node('p','运行一次判断或发送报修消息后，可以在这里查看工具调用与节点。'));});
document.addEventListener('keydown',e=>{if(e.key==='Escape')toggleTrace(false);if((e.metaKey||e.ctrlKey)&&e.key==='Enter'&&!e.isComposing){e.preventDefault();if(view==='judge')runJudge();else sendChat($('chat-input').value.trim());}});
window.addEventListener('hashchange',()=>{const next=location.hash==='#repair'?'repair':'judge';if(next!==view)selectView(next);});
const mobile=node('button','报修助手','mobile-switch');mobile.id='mobile-switch';mobile.addEventListener('click',()=>selectView(view==='judge'?'repair':'judge'));document.querySelector('.top-actions').prepend(mobile);
async function checkHealth(){try{const response=await fetch('/api/health');if(!response.ok)throw new Error();const data=await response.json();$('connection').textContent='';const dot=node('i');$('connection').append(dot,document.createTextNode(data.mcp_online?'MCP 已连接':'MCP 未连接'));$('connection').classList.toggle('offline',!data.mcp_online);$('model-name').textContent=data.model_configured?data.model.replace('deepseek-flash','DeepSeek Flash'):'模型待配置';}catch{$('connection').textContent='服务未连接';$('connection').classList.add('offline');}}
selectTemplate('route');renderHistory();checkHealth();if(location.hash==='#repair')selectView('repair');
