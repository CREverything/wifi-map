import L from 'leaflet';

// Leaflet owns the image's geographic bounds and transforms it during pan/zoom.
export const HeatLayer = L.Layer.extend({
  initialize(rows,opacity,colors) { this.rows=rows;this.opacity=opacity;this.colors=colors; },
  onAdd(map) {this.map=map;map.on('moveend zoomend resize',this.draw,this);this.draw();},
  onRemove(map) {map.off('moveend zoomend resize',this.draw,this);if(this.image)map.removeLayer(this.image);this.image=null;},
  draw() {
    const map=this.map,size=map.getSize(),scale=3;
    if(!size.x||!size.y)return;
    const canvas=document.createElement('canvas');canvas.width=Math.ceil(size.x/scale);canvas.height=Math.ceil(size.y/scale);
    const w=canvas.width,h=canvas.height,weights=new Float32Array(w*h),values=new Float32Array(w*h);
    for(const row of this.rows){
      const point=map.latLngToContainerPoint([row.latitude,row.longitude]);
      const east=map.latLngToContainerPoint([row.latitude,row.longitude+row.radiusMeters/(111320*Math.max(.01,Math.cos(row.latitude*Math.PI/180)))]);
      const cx=point.x/scale,cy=point.y/scale,r=Math.max(1,Math.abs(east.x-point.x)/scale);
      const x0=Math.max(0,Math.floor(cx-r)),x1=Math.min(w-1,Math.ceil(cx+r)),y0=Math.max(0,Math.floor(cy-r)),y1=Math.min(h-1,Math.ceil(cy+r));
      for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
        const d=((x-cx)**2+(y-cy)**2)/(r*r);if(d>=1)continue;
        const weight=Math.exp(-4*d)*(1-d),i=y*w+x;
        weights[i]+=weight;values[i]+=weight*row.intensity;
      }
    }
    const ctx=canvas.getContext('2d'),pixels=ctx.createImageData(w,h),[low,high]=this.colors;
    for(let i=0;i<weights.length;i++){
      if(!weights[i])continue;const t=values[i]/weights[i],j=i*4;
      for(let c=0;c<3;c++)pixels.data[j+c]=low[c]+(high[c]-low[c])*t;
      pixels.data[j+3]=Math.min(1,weights[i])*this.opacity/100*220;
    }
    ctx.putImageData(pixels,0,0);
    const bounds=L.latLngBounds(map.containerPointToLatLng([0,size.y]),map.containerPointToLatLng([size.x,0]));
    const url=canvas.toDataURL();
    if(this.image){this.image.setUrl(url);this.image.setBounds(bounds);}
    else this.image=L.imageOverlay(url,bounds,{interactive:false,className:'signal-heatmap',zIndex:1}).addTo(map);
  }
});
