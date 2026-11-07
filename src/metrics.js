export const METRICS = [
  {id:'connection',label:'Connection strength',low:'Weak',high:'Strong',colors:[[239,220,250],[107,35,146]],max:1},
  {id:'downloadMbps',label:'Download speed',low:'0 Mbps',high:'200+ Mbps',colors:[[215,242,249],[20,91,146]],max:200},
  {id:'uploadMbps',label:'Upload speed',low:'0 Mbps',high:'100+ Mbps',colors:[[255,229,237],[226,58,111]],max:100},
  {id:'latencyMs',label:'Latency',low:'0 ms',high:'200+ ms',colors:[[231,235,237],[46,52,58]],max:200}
];
METRICS.push({id:'modelIntensity',label:'Model intensity',low:'Low',high:'High',colors:[[255,225,220],[185,30,52]],max:1});
export function metricRows(rows,metric){if(metric.id==='modelIntensity')return rows.filter(r=>!r.metrics);return rows.filter(r=>Number.isFinite(r.metrics?.[metric.id])).map(r=>({...r,intensity:Math.min(1,Math.max(0,r.metrics[metric.id]/metric.max))}));}
