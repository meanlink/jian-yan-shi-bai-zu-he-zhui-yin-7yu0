import {restorePoints,restoreRuns} from '../api/entities.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {PointStatus,RunStatus,RunMode} from '../constants/enums.js';
const TABLE_LABELS={datasets:'数据批次',jobs:'分析任务',reports:'分发计划',deliveries:'归档记录'};
let activeRun=0;
function diffTable(diff){
 return '<div class="table-wrap"><table><thead><tr><th>实体</th><th>当前</th><th>恢复点</th><th>新增将丢弃</th><th>缺失将找回</th><th>修改将还原</th></tr></thead><tbody>'+Object.keys(TABLE_LABELS).map(k=>{const t=diff.tables[k]||{};return '<tr><td>'+TABLE_LABELS[k]+'</td><td>'+(t.current??0)+'</td><td>'+(t.snapshot??0)+'</td><td>'+(t.new??0)+'</td><td>'+(t.missing??0)+'</td><td>'+(t.changed??0)+'</td></tr>';}).join('')+'</tbody></table></div>';
}
function discardList(diff){
 const html=Object.keys(TABLE_LABELS).map(k=>{const d=diff.discard[k]||{total:0,items:[]};if(!d.total)return '';
  return '<p class="eyebrow">'+TABLE_LABELS[k]+' · '+d.total+' 项将丢弃</p><ul class="discard">'+d.items.map(i=>'<li><span>'+esc(i.kind)+'</span>'+esc(i.label)+'</li>').join('')+(d.total>d.items.length?'<li>… 其余 '+(d.total-d.items.length)+' 项从略</li>':'')+'</ul>';}).join('');
 return html||'<p class="hint">恢复点之后没有后续变更，切换不丢弃任何内容。</p>';
}
function activePanel(r){
 const s=r.summary||{},diff=s.diff,ver=s.verification,point=s.point||{};
 if(r.mode==='restore'&&r.status==='preview'&&diff)return '<section class="panel restore-active"><div class="section-title"><h2>恢复预览 · 将丢弃的后续变更</h2><span>恢复到「'+esc(point.name||'')+'」</span></div>'+diffTable(diff)+discardList(diff)+'<p class="warning">确认后站点写入短暂封闭，核对附件与关联后一次性切换，失败仍用原站。确认前若站点有新写入，本预览自动作废。</p><button class="primary" data-confirm="'+r.id+'">确认恢复到此时点</button></section>';
 if(r.mode==='drill'&&r.status==='completed'&&diff)return '<section class="panel"><div class="section-title"><h2>演练前后数据对比</h2><span>未改动线上数据</span></div>'+diffTable(diff)+(ver?'<p class="hint">附件核对 '+ver.attachments.ok+'/'+ver.attachments.total+' 一致'+(ver.problems&&ver.problems.length?'；问题：'+esc(ver.problems.join('；')):'')+'</p>':'')+'</section>';
 if(r.status==='failed')return '<section class="panel"><div class="section-title"><h2>'+esc(RunMode[r.mode]||'操作')+'失败原因</h2></div><p class="warning">'+esc(r.error||'未知原因')+'</p>'+(r.mode==='restore'?'<button class="button" data-resume="'+r.id+'">排除原因后继续同次恢复</button>':'')+'</section>';
 if(r.status==='restoring')return '<section class="panel"><div class="section-title"><h2>恢复进行中</h2><span>步骤 '+esc(r.step||'-')+'</span></div><p class="hint">站点写入已封闭；若进程中断，回到本页可继续同次操作，重试不会重复替换。</p><button class="button" data-resume="'+r.id+'">继续同次恢复</button></section>';
 if(r.mode==='restore'&&r.status==='completed')return '<section class="panel"><div class="section-title"><h2>恢复完成</h2></div><p class="hint">站点已切换到恢复点「'+esc(point.name||'')+'」。恢复的分发计划保持暂停，重新启用后才继续，且从启用时刻起算、不补发旧期。</p></section>';
 return '';
}
export async function restorePage(){
 if(session.user.role!=='admin')return heading('06 / RECOVERY','站点恢复点','整站快照与恢复由业务负责人管理。')+'<p class="empty">仅业务负责人可管理站点恢复。</p>';
 const [points,runs]=await Promise.all([restorePoints.list(),restoreRuns.list()]);
 const active=runs.find(r=>r.id===activeRun)||runs.find(r=>r.status==='preview')||runs.find(r=>r.status==='restoring')||null;
 return heading('06 / RECOVERY','站点恢复点','整站快照对应同一时点：数据批次、分析、计划与附件一起留存。恢复前核对将丢弃的变更，演练可比对前后数据。','<button class="button" id="refresh-restore">刷新 ↻</button>')
 +'<div class="report-grid"><section class="panel"><div class="section-title"><h2>创建恢复点</h2></div><form id="point-form"><label>恢复点名称<input name="name" required minlength="2" maxlength="160" value="误删排查前 · 整站快照"></label><button type="submit" class="primary">立即备份整站</button></form><p class="hint">备份期间可继续接入与计算；快照内所有数据对应同一时点。</p></section>'
 +'<section><div class="section-title"><h2>恢复点</h2><span>'+points.filter(p=>p.status==='ready').length+' 个就绪</span></div><div class="schedule-list">'
 +points.map(p=>'<article><div><strong>'+esc(p.name)+'</strong><p>'+date(p.created_at)+' · '+esc(p.created_by)+' · 批次 '+(p.counts.datasets||0)+' / 任务 '+(p.counts.jobs||0)+' / 计划 '+(p.counts.reports||0)+' / 归档 '+(p.counts.deliveries||0)+'</p><small><span class="status '+esc(p.status)+'">'+esc(PointStatus[p.status]||p.status)+'</span>'+(p.error?' · '+esc(p.error):'')+'</small></div><div class="row-actions"><button class="button small" data-preview="'+p.id+'" '+(p.status!=='ready'?'disabled':'')+'>预览恢复</button><button class="button small" data-drill="'+p.id+'" '+(p.status!=='ready'?'disabled':'')+'>演练</button></div></article>').join('')
 +(!points.length?'<p class="empty">还没有恢复点。先创建一个整站快照。</p>':'')+'</div></section></div>'
 +(active?activePanel(active):'')
 +'<section class="panel"><div class="section-title"><h2>操作记录</h2><span>预览、恢复与演练</span></div><div class="schedule-list">'
 +runs.map(r=>'<article><div><strong>#'+r.id+' '+esc(RunMode[r.mode]||r.mode)+' · '+esc(RunStatus[r.status]||r.status)+'</strong><p>'+esc(r.created_by)+' · '+date(r.created_at)+(r.step&&r.status==='restoring'?' · 步骤 '+esc(r.step):'')+'</p>'+(r.error?'<small>'+esc(r.error)+'</small>':'')+'</div><div class="row-actions"><button class="button small" data-inspect="'+r.id+'">查看</button>'+(r.status==='restoring'||r.status==='failed'?'<button class="button small" data-resume="'+r.id+'">继续</button>':'')+'</div></article>').join('')
 +(!runs.length?'<p class="empty">还没有预览、恢复或演练记录。</p>':'')+'</div></section>';
}
export function bindRestore(refresh){
 const home=document.querySelector('#refresh-restore');
 if(!home)return;
 home.onclick=refresh;
 submit(document.querySelector('#point-form'),async f=>{const p=await restorePoints.create({name:f.get('name')});notify(p.status==='ready'?'恢复点已就绪，快照对应同一时点':'备份未成功：'+(p.error||''));await refresh();});
 document.querySelectorAll('[data-preview]').forEach(b=>b.onclick=async()=>{try{const r=await restorePoints.preview(b.dataset.preview);activeRun=r.id;await refresh();}catch(e){notify(e.message,true);}});
 document.querySelectorAll('[data-drill]').forEach(b=>b.onclick=async()=>{try{const r=await restorePoints.drill(b.dataset.drill);activeRun=r.id;notify(r.status==='completed'?'演练完成，未改动线上数据':'演练未通过：'+(r.error||''));await refresh();}catch(e){notify(e.message,true);}});
 const c=document.querySelector('[data-confirm]');
 if(c)c.onclick=async()=>{if(!confirm('确认切换？站点写入将短暂封闭，核对附件与关联后一次性切换。'))return;try{const r=await restoreRuns.confirm(c.dataset.confirm);activeRun=r.id;notify(r.status==='completed'?'恢复完成，站点已切换':'恢复未成功：'+(r.error||''),r.status!=='completed');await refresh();}catch(e){notify(e.message,true);await refresh();}};
 document.querySelectorAll('[data-resume]').forEach(b=>b.onclick=async()=>{try{const r=await restoreRuns.resume(b.dataset.resume);activeRun=r.id;notify(r.status==='completed'?'恢复完成，站点已切换':'同次恢复已继续：'+(RunStatus[r.status]||r.status));await refresh();}catch(e){notify(e.message,true);await refresh();}});
 document.querySelectorAll('[data-inspect]').forEach(b=>b.onclick=async()=>{activeRun=Number(b.dataset.inspect);await refresh();});
}
