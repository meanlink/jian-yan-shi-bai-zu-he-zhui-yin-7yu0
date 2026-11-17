import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const restorePoints={list:()=>api('/restore-points'),create:data=>api('/restore-points',{method:'POST',body:JSON.stringify(data)}),preview:id=>api('/restore-points/'+id+'/preview',{method:'POST'}),drill:id=>api('/restore-points/'+id+'/drill',{method:'POST'})};
export const restoreRuns={list:()=>api('/restore-runs'),get:id=>api('/restore-runs/'+id),confirm:id=>api('/restore-runs/'+id+'/confirm',{method:'POST'}),resume:id=>api('/restore-runs/'+id+'/resume',{method:'POST'})};
