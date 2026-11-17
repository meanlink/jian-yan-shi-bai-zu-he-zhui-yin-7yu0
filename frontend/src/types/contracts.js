/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,name:string,status:'capturing'|'ready'|'failed',counts:Object,checksum:string,error:string}} RestorePoint */
/** @typedef {{id:number,point_id:number,mode:'restore'|'drill',status:'preview'|'restoring'|'completed'|'failed',step:string,summary:Object,error:string}} RestoreRun */
export {};
