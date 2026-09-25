// RIIS — charts (SVG, hand-rolled)
const { useState: useState_c, useMemo: useMemo_c, useRef: useRef_c, useEffect: useEffect_c } = React;

// Multi-series line chart with synchronized crosshair
function LineChart({ series, xLabels, w=700, h=220, pad={t:16,r:20,b:28,l:36}, yFmt=(v)=>v, showLegend=true }){
  const iw = w - pad.l - pad.r;
  const ih = h - pad.t - pad.b;
  const [hi,setHi] = useState_c(-1);
  const all = series.flatMap(s=>s.data||[]);
  const n = xLabels.length;
  if (!all.length || n < 2) {
    return (<div style={{width:w,height:h,display:'grid',placeItems:'center',fontSize:12,color:'var(--text-lo)',fontFamily:'JetBrains Mono'}}>Waiting for live forecast data…</div>);
  }
  const yMax = Math.ceil(Math.max(...all)*1.15);
  const yMin = 0;
  const xAt = i => pad.l + (i/(n-1))*iw;
  const yAt = v => pad.t + (1 - (v-yMin)/(yMax-yMin))*ih;
  const ticks = 4;
  return (
    <div style={{position:"relative"}}>
      <svg width={w} height={h} onMouseLeave={()=>setHi(-1)} onMouseMove={(e)=>{
        const rect = e.currentTarget.getBoundingClientRect();
        const x = e.clientX - rect.left - pad.l;
        const i = Math.round((x/iw)*(n-1));
        if(i>=0 && i<n) setHi(i);
      }}>
        {/* Y grid */}
        {Array.from({length:ticks+1}).map((_,i)=>{
          const y = pad.t + (i/ticks)*ih;
          const v = yMax - (i/ticks)*(yMax-yMin);
          return (<g key={i}>
            <line x1={pad.l} x2={pad.l+iw} y1={y} y2={y} stroke="rgba(120,180,255,0.08)"/>
            <text x={pad.l-8} y={y+3} fontSize="10" textAnchor="end" fill="var(--text-lo)" fontFamily="JetBrains Mono">{yFmt(Math.round(v))}</text>
          </g>);
        })}
        {/* X labels */}
        {xLabels.map((l,i)=>(
          <text key={i} x={xAt(i)} y={h-8} fontSize="10" textAnchor="middle" fill="var(--text-lo)" fontFamily="JetBrains Mono">{l}</text>
        ))}
        {/* series */}
        {series.map((s,si)=>{
          const path = s.data.map((v,i)=>(i?"L":"M")+xAt(i).toFixed(1)+" "+yAt(v).toFixed(1)).join(" ");
          const area = path+` L ${xAt(n-1)} ${pad.t+ih} L ${xAt(0)} ${pad.t+ih} Z`;
          return (<g key={si}>
            {s.fill!==false && <path d={area} fill={s.color} opacity="0.10"/>}
            <path d={path} stroke={s.color} strokeWidth="2" fill="none" strokeLinecap="round"/>
            {s.data.map((v,i)=>(
              <circle key={i} cx={xAt(i)} cy={yAt(v)} r={hi===i?4:2} fill={s.color} stroke="#0A121C" strokeWidth={hi===i?2:0}/>
            ))}
          </g>);
        })}
        {/* Crosshair */}
        {hi>=0 && (
          <line x1={xAt(hi)} x2={xAt(hi)} y1={pad.t} y2={pad.t+ih} stroke="var(--cyan)" strokeDasharray="3 3" opacity=".6"/>
        )}
      </svg>
      {/* Legend */}
      {showLegend && (
        <div style={{display:"flex",gap:14,justifyContent:"flex-end",fontSize:11,color:"var(--text-mid)",marginTop:-4,padding:"0 12px"}}>
          {series.map((s,i)=>(
            <span key={i} style={{display:"inline-flex",alignItems:"center",gap:5}}>
              <span style={{width:10,height:2,background:s.color,borderRadius:1}}/>{s.name}
            </span>
          ))}
        </div>
      )}
      {/* Tooltip */}
      {hi>=0 && (
        <div style={{
          position:"absolute", left: Math.min(xAt(hi)+10, w-160), top:pad.t,
          background:"rgba(10,18,28,0.95)",border:"1px solid var(--stroke-2)",borderRadius:8,padding:"8px 10px",
          fontSize:11,minWidth:140,pointerEvents:"none",zIndex:5
        }}>
          <div className="mono" style={{color:"var(--text-lo)",fontSize:10,letterSpacing:".08em",marginBottom:4}}>{xLabels[hi]}</div>
          {series.map((s,i)=>(
            <div key={i} style={{display:"flex",justifyContent:"space-between",gap:10,color:"var(--text-hi)"}}>
              <span><span style={{display:"inline-block",width:8,height:8,background:s.color,borderRadius:2,marginRight:5}}/>{s.name}</span>
              <b className="mono">{yFmt(s.data[hi])}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Bar chart (vertical)
function BarChart({ data, w=520, h=180, pad={t:10,r:12,b:24,l:30}, color="var(--cyan)", yFmt=(v)=>v }){
  const iw = w - pad.l - pad.r;
  const ih = h - pad.t - pad.b;
  const yMax = Math.max(...data.map(d=>d.v))*1.15;
  const bw = iw/data.length * 0.6;
  return (
    <svg width={w} height={h}>
      {[0,1,2,3].map(i=>{
        const y = pad.t + (i/3)*ih;
        return <line key={i} x1={pad.l} x2={pad.l+iw} y1={y} y2={y} stroke="rgba(120,180,255,0.08)"/>;
      })}
      {data.map((d,i)=>{
        const x = pad.l + (i+0.2)*(iw/data.length);
        const bh = (d.v/yMax)*ih;
        return (<g key={i}>
          <rect x={x} y={pad.t+ih-bh} width={bw} height={bh} fill={d.c||color} rx="3"
            style={{filter:`drop-shadow(0 0 4px ${d.c||color})`}} opacity=".85"/>
          <text x={x+bw/2} y={h-8} fontSize="10" textAnchor="middle" fill="var(--text-lo)" fontFamily="JetBrains Mono">{d.l}</text>
          <text x={x+bw/2} y={pad.t+ih-bh-5} fontSize="10" textAnchor="middle" fill="var(--text-hi)" fontFamily="JetBrains Mono">{yFmt(d.v)}</text>
        </g>);
      })}
    </svg>
  );
}

// Donut / Pie
function Donut({ segments, size=140, thickness=22, label, sublabel }){
  const r = (size-thickness)/2;
  const cx = size/2;
  const total = segments.reduce((a,b)=>a+b.v,0);
  let cursor = -Math.PI/2;
  return (
    <div style={{position:"relative",width:size,height:size}}>
      <svg width={size} height={size}>
        {segments.map((s,i)=>{
          const ang = (s.v/total)*Math.PI*2;
          const x1 = cx + r*Math.cos(cursor), y1 = cx + r*Math.sin(cursor);
          const x2 = cx + r*Math.cos(cursor+ang), y2 = cx + r*Math.sin(cursor+ang);
          const large = ang > Math.PI ? 1 : 0;
          const path = `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
          const el = <path key={i} d={path} stroke={s.c} strokeWidth={thickness} fill="none" strokeLinecap="round"/>;
          cursor += ang;
          return el;
        })}
      </svg>
      <div style={{position:"absolute",inset:0,display:"grid",placeItems:"center",textAlign:"center",lineHeight:1.1}}>
        <div>
          <div style={{fontSize:size*.20,fontWeight:700}} className="num">{label}</div>
          {sublabel && <div className="k" style={{marginTop:4}}>{sublabel}</div>}
        </div>
      </div>
    </div>
  );
}

// Heatmap grid (rows × cols)
function Heatmap({ rows, cols, data, w=560, h=180, colorScale }){
  const cw = w/cols.length;
  const ch = h/rows.length;
  const cs = colorScale || ((v)=>{
    const t = Math.max(0,Math.min(1,v/100));
    const rr = Math.round(15 + t*230);
    const gg = Math.round(120 - t*80);
    const bb = Math.round(240 - t*180);
    return `rgba(${rr},${gg},${bb},${0.3+t*0.6})`;
  });
  return (
    <svg width={w} height={h+40}>
      {rows.map((r,ri)=>(
        <text key={ri} x="0" y={ri*ch + ch*0.6+16} fontSize="10" fill="var(--text-lo)" fontFamily="JetBrains Mono">{r}</text>
      ))}
      <g transform="translate(40,16)">
        {rows.map((r,ri)=>(
          cols.map((c,ci)=>{
            const v = data[ri]?.[ci] ?? 0;
            return <rect key={ri+"_"+ci} x={ci*(w-40)/cols.length} y={ri*ch} width={(w-40)/cols.length-2} height={ch-2} fill={cs(v)} rx="2"/>;
          })
        ))}
        {cols.map((c,i)=>(
          <text key={i} x={i*(w-40)/cols.length + ((w-40)/cols.length-2)/2} y={rows.length*ch+14} fontSize="10" textAnchor="middle" fill="var(--text-lo)" fontFamily="JetBrains Mono">{c}</text>
        ))}
      </g>
    </svg>
  );
}

Object.assign(window,{ LineChart, BarChart, Donut, Heatmap });
