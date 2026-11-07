// Deterministic fictional San Diego clusters, never presented as observations.
export function createSimulation() {
  let seed=418;
  const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
  const centers=[[32.7157,-117.1611,'Downtown'],[32.7285,-117.1513,'Balboa Park'],[32.723,-117.168,'Little Italy'],[32.709,-117.153,'East Village'],[32.737,-117.18,'Airport vicinity']];
  return {version:1,summary:'SIMULATION — 200 fictional points around San Diego. Purple, blue, pink, and gray show simulated metrics, not measured Wi-Fi quality or live model findings.',areas:centers.flatMap(([lat,lng,label])=>Array.from({length:40},()=>{
    const angle=random()*Math.PI*2, distance=Math.sqrt(random())*.004;
    return {latitude:lat+Math.sin(angle)*distance,longitude:lng+Math.cos(angle)*distance*1.18,radiusMeters:180+random()*180,intensity:.2+random()*.8,metrics:{connection:random(),downloadMbps:10+random()*240,uploadMbps:5+random()*110,latencyMs:5+random()*210},explanation:`Fictional ${label} sample. Generated for interface testing only.`};
  }))};
}
