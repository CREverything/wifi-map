export function validateModelResponse(input) {
  if (!input || input.version !== 1 || !Array.isArray(input.areas) || input.areas.length > 10000) throw new Error('Expected version: 1 and an areas array (maximum 10,000 areas).');
  if (typeof input.summary !== 'string' || input.summary.length > 4000) throw new Error('summary must be text of at most 4,000 characters.');
  const areas = input.areas.map((row, i) => {
    if (!row || typeof row !== 'object') throw new Error(`Area ${i+1} must be an object.`);
    const {latitude,longitude,radiusMeters,intensity,explanation} = row;
    if (![latitude,longitude,radiusMeters,intensity].every(Number.isFinite) || Math.abs(latitude)>90 || Math.abs(longitude)>180 || radiusMeters<=0 || radiusMeters>100000 || intensity<0 || intensity>1) throw new Error(`Area ${i+1}: invalid coordinates, radius (0–100,000 m), or intensity (0–1).`);
    if (typeof explanation !== 'string' || explanation.length>2000) throw new Error(`Area ${i+1}: explanation must be text of at most 2,000 characters.`);
    const metrics={};
    if(row.metrics!==undefined){
      if(!row.metrics||typeof row.metrics!=='object'||Array.isArray(row.metrics))throw new Error('metrics must be an object.');
      for(const key of ['connection','downloadMbps','uploadMbps','latencyMs']){
        const value=row.metrics[key];if(value==null)continue;
        if(!Number.isFinite(value)||value<0||(key==='connection'&&value>1))throw new Error('Invalid '+key+' metric.');
        metrics[key]=value;
      }
    }
    return {latitude,longitude,radiusMeters,intensity,explanation,...(row.metrics!==undefined?{metrics}:{})};
  });
  return {version:1,summary:input.summary,areas};
}
export const demo = {version:1,summary:'Illustrative model response only. These areas are synthetic, not live Wi-Fi findings. Red intensity is supplied by the model; its meaning will be defined with your backend.',areas:[
  {latitude:32.7157,longitude:-117.1611,radiusMeters:150,intensity:0.9,explanation:'Example area with high overlay intensity.'},
  {latitude:32.7181,longitude:-117.1642,radiusMeters:100,intensity:0.5,explanation:'Example area with medium overlay intensity.'},
  {latitude:32.7129,longitude:-117.1576,radiusMeters:120,intensity:0.2,explanation:'Example area with low overlay intensity.'}
]};
