// RIIS — Community feedback, Historical analytics, Admin
const { useState: useState_cha, useEffect: useEffect_cha } = React;

// Model registry (GET /api/ml/models) → table rows
const MODEL_NAMES = { xgboost: "XGBoost", random_forest: "Random Forest", gradient_boost: "Gradient Boost",
  ensemble_vote: "Ensemble Vote", lstm_impact: "LSTM-Impact", transformer: "Transformer", convlstm: "ConvLSTM", convgru: "ConvGRU" };
function modelAgo(iso){
  if (!iso) return "—";
  const h = (Date.now() - new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime()) / 3.6e6;
  return h < 1 ? `${Math.max(1, Math.round(h * 60))} min ago` : h < 48 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} d ago`;
}
function modelRowsFromRegistry(reg){
  return Object.keys(MODEL_NAMES).filter(k => reg[k]).map(k => {
    const e = reg[k], m = e.metrics || {}, spatial = e.family === "spatial";
    return {
      key: k, name: MODEL_NAMES[k], family: e.family, task: String(e.task || "").replace(/_/g, " "),
      primary: spatial ? `${m.rmse_mm} mm RMSE` : `${(m.accuracy * 100).toFixed(1)}%`,
      primaryPct: spatial ? null : m.accuracy * 100,
      secondary: spatial ? `CSI₅ ${m.csi_5mm}` : `F1 ${m.macro_f1}`,
      tertiary: spatial ? `persist. ${((e.persistence_baseline || {}).rmse_mm)} mm` : (m.heavy_rain_auc != null ? m.heavy_rain_auc.toFixed(3) : "—"),
      rows: Number(e.train_rows || e.train_windows || 0).toLocaleString(),
      secs: e.train_seconds != null ? `${Math.round(e.train_seconds)} s` : "—",
      trained: modelAgo(e.trained_at),
    };
  });
}

function CommunityScreen(){
  const nowStr = new Date().toISOString().slice(0,19).replace('T',' ') + ' IST';
  const gpsStr = `${RIIS.location.lat.toFixed(4)}°N ${RIIS.location.lon.toFixed(4)}°E · Auto`;
  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">CITIZENS <b>Community Feedback</b></div>
          <h1 style={{marginTop:6}}>Ground-truth reports from {RIIS.location.city || "Local"} citizens</h1>
          <p style={{marginTop:4}}>Verified reports flow back into training data for continuous model retraining · <b className="mono" style={{color:"var(--text-hi)"}}>1,284</b> reports today</p>
        </div>
        <div className="id">FEEDBACK LOOP · v2 · RETRAIN NIGHTLY</div>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:16}}>
        {/* Report submission */}
        <div className="panel brackets">
          <div className="panel-hd"><h3>Submit a Report</h3><span className="sub">Citizen contribution</span></div>
          <div className="panel-bd">
            <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:8}}>
              {[
                ["Rainfall",Icon.droplet],["Flood Photo",Icon.camera],["Flood Video",Icon.camera],["Waterlogging",Icon.wave],
                ["Road Damage",Icon.route],["Tree Fall",Icon.leaf],["Crop Damage",Icon.leaf],["River Overflow",Icon.wave]
              ].map(([k,ic],i)=>(
                <button key={i} style={{padding:16,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:12,color:"var(--text-hi)",display:"flex",flexDirection:"column",alignItems:"center",gap:8,transition:".2s",cursor:"pointer"}}
                        onMouseEnter={e=>{e.currentTarget.style.borderColor="var(--cyan)";e.currentTarget.style.background="rgba(34,211,238,0.06)"}}
                        onMouseLeave={e=>{e.currentTarget.style.borderColor="var(--stroke)";e.currentTarget.style.background="rgba(10,18,28,0.5)"}}>
                  <span style={{color:"var(--cyan)"}}>{ic}</span>
                  <span style={{fontSize:11.5,fontWeight:500}}>{k}</span>
                </button>
              ))}
            </div>

            <div style={{marginTop:16,padding:16,background:"rgba(10,18,28,0.5)",border:"1px dashed var(--stroke-2)",borderRadius:12,textAlign:"center"}}>
              <div style={{color:"var(--cyan)",marginBottom:8}}>{Icon.camera}</div>
              <div style={{fontSize:13,fontWeight:500}}>Drop photo or video here</div>
              <div style={{fontSize:11,color:"var(--text-lo)",marginTop:4}} className="mono">JPG · PNG · MP4 · MAX 25 MB · GPS AUTO-TAGGED</div>
            </div>

            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginTop:12}}>
              <div><div className="k mb2">GPS LOCATION</div><div className="mono" style={{padding:"9px 12px",background:"rgba(10,18,28,0.6)",border:"1px solid var(--stroke)",borderRadius:8,fontSize:12}}>{gpsStr}</div></div>
              <div><div className="k mb2">TIMESTAMP</div><div className="mono" style={{padding:"9px 12px",background:"rgba(10,18,28,0.6)",border:"1px solid var(--stroke)",borderRadius:8,fontSize:12}}>{nowStr}</div></div>
            </div>
            <div style={{marginTop:10}}>
              <div className="k mb2">DESCRIPTION</div>
              <textarea rows="3" placeholder="Water knee-deep near Velachery bus stand. Traffic halted." style={{width:"100%",background:"rgba(10,18,28,0.6)",border:"1px solid var(--stroke)",borderRadius:8,padding:10,color:"var(--text-hi)",fontSize:12.5,outline:"none",resize:"none",fontFamily:"inherit"}}/>
            </div>
            <button className="btn primary mt3">Submit Report</button>
          </div>
        </div>

        <div className="vstack" style={{gap:16}}>
          <div className="panel brackets">
            <div className="panel-hd"><h3>Report Stats · Today</h3></div>
            <div className="panel-bd">
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10}}>
                {[
                  ["1,284","Reports today","#22D3EE"],
                  ["847","AI-verified","#10B981"],
                  ["68%","Verification rate","#7DD3FC"],
                  ["+412","Training samples","#A78BFA"]
                ].map(([v,l,c],i)=>(
                  <div key={i} style={{padding:12,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:10}}>
                    <div style={{fontSize:24,fontWeight:700,color:c,letterSpacing:"-0.02em"}} className="num">{v}</div>
                    <div className="k" style={{marginTop:4}}>{l}</div>
                  </div>
                ))}
              </div>
              <div style={{marginTop:14}}>
                <div className="k mb2">TYPE DISTRIBUTION</div>
                <Donut segments={[
                  {v:412,c:"#22D3EE"},{v:264,c:"#3B82F6"},{v:186,c:"#F97316"},{v:148,c:"#A78BFA"},{v:88,c:"#F59E0B"},{v:186,c:"#7DD3FC"}
                ]} size={120} label="1,284" sublabel="reports"/>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:4,fontSize:11,color:"var(--text-mid)",marginTop:10}}>
                  <span><span style={{display:"inline-block",width:8,height:8,background:"#22D3EE",borderRadius:2,marginRight:5}}/>Waterlogging</span>
                  <span><span style={{display:"inline-block",width:8,height:8,background:"#3B82F6",borderRadius:2,marginRight:5}}/>Flood photo</span>
                  <span><span style={{display:"inline-block",width:8,height:8,background:"#F97316",borderRadius:2,marginRight:5}}/>Road damage</span>
                  <span><span style={{display:"inline-block",width:8,height:8,background:"#A78BFA",borderRadius:2,marginRight:5}}/>Tree fall</span>
                  <span><span style={{display:"inline-block",width:8,height:8,background:"#F59E0B",borderRadius:2,marginRight:5}}/>Crop</span>
                  <span><span style={{display:"inline-block",width:8,height:8,background:"#7DD3FC",borderRadius:2,marginRight:5}}/>Other</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Recent reports */}
      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd"><h3>Recent Verified Reports</h3><span className="live"><span className="d"/>LIVE FEED</span></div>
        <div className="panel-bd" style={{padding:0}}>
          <table className="data">
            <thead><tr><th>Time</th><th>User</th><th>Ward</th><th>Type</th><th>Depth / Note</th><th>AI Status</th><th>Upvotes</th><th>Fed into Retrain?</th></tr></thead>
            <tbody>
              {RIIS.reports.map((r,i)=>(
                <tr key={r.id}>
                  <td className="mono">{r.ago}</td>
                  <td className="mono" style={{color:"var(--cyan)"}}>{r.user}</td>
                  <td>{r.ward}</td>
                  <td>{r.type}</td>
                  <td className="mono">{r.depth}</td>
                  <td>{r.verified
                    ? <span className="sev" style={{color:"#5EEAD4",background:"rgba(16,185,129,0.14)"}}>VERIFIED</span>
                    : <span className="sev" style={{color:"#FDBA74",background:"rgba(249,115,22,0.14)"}}>REVIEWING</span>}
                  </td>
                  <td className="mono">↑ {r.upvotes}</td>
                  <td>{r.verified? <span style={{color:"#5EEAD4"}}>{Icon.check}</span> : <span style={{color:"var(--text-lo)"}}>—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function HistoryScreen(){
  const yrs = Array.from({length:12},(_,i)=>String(2014+i));
  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">ANALYTICS <b>Historical Dashboard</b></div>
          <h1 style={{marginTop:6}}>12-year climate &amp; disaster analytics</h1>
          <p style={{marginTop:4}}>Rainfall trends, flood frequency, crop damage &amp; reservoir behavior for Tamil Nadu · with climate-change indicators</p>
        </div>
        <div className="id">DATASET · IMD 2014–2026 · +ERA5</div>
      </div>

      {/* KPI */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12,marginBottom:16}}>
        {[
          ["Avg Annual Rain","1,478 mm","#22D3EE","+9% vs 2014"],
          ["Extreme Events","6 / yr","#F97316","+40% since 2014"],
          ["Crop Loss Index","47%","#F59E0B","+12% decade"],
          ["Avg Reservoir Fill","78%","#10B981","+4% decade"],
        ].map(([k,v,c,s],i)=>(
          <div key={i} className="panel" style={{padding:14,borderLeft:`3px solid ${c}`}}>
            <div className="k">{k}</div>
            <div className="num" style={{fontSize:24,fontWeight:700,color:c,letterSpacing:"-0.02em",marginTop:2}}>{v}</div>
            <div style={{fontSize:11,color:"var(--text-mid)",marginTop:2}}>{s}</div>
          </div>
        ))}
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16}}>
        <div className="panel brackets">
          <div className="panel-hd"><h3>10-Year Rainfall Trend · Chennai</h3><span className="sub">Annual mm</span></div>
          <div className="panel-bd">
            <LineChart w={620} h={220} xLabels={yrs} series={[
              { name:"Annual Rainfall (mm)", color:"#22D3EE", data: RIIS.historical.yearsRain },
              { name:"10-yr mean",           color:"rgba(120,180,255,0.4)", data: yrs.map(()=>1478), fill:false }
            ]}/>
          </div>
        </div>
        <div className="panel brackets">
          <div className="panel-hd"><h3>Major Flood Events per Year</h3></div>
          <div className="panel-bd">
            <BarChart w={620} h={220} data={yrs.map((y,i)=>({l:y.slice(2),v:RIIS.historical.yearsFlood[i],c:RIIS.historical.yearsFlood[i]>5?"#EF4444":RIIS.historical.yearsFlood[i]>3?"#F97316":"#F59E0B"}))}/>
          </div>
        </div>
        <div className="panel brackets">
          <div className="panel-hd"><h3>Crop Damage Index</h3></div>
          <div className="panel-bd">
            <LineChart w={620} h={220} xLabels={yrs} series={[
              { name:"Crop Loss Index (%)", color:"#F97316", data: RIIS.historical.yearsCrop }
            ]}/>
          </div>
        </div>
        <div className="panel brackets">
          <div className="panel-hd"><h3>Average Reservoir Fill</h3></div>
          <div className="panel-bd">
            <LineChart w={620} h={220} xLabels={yrs} series={[
              { name:"Reservoir Fill (%)", color:"#3B82F6", data: RIIS.historical.yearsRes }
            ]}/>
          </div>
        </div>
      </div>

      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd"><h3>Seasonal Heat Map — Rainfall (mm)</h3><span className="sub">Monthly · 12 years</span></div>
        <div className="panel-bd">
          <Heatmap w={1300} h={240}
            rows={yrs}
            cols={["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]}
            data={yrs.map((_,i)=>[8,12,20,42,68,88,124,164,182,318,412,168].map(v=>v+Math.round((Math.sin(i)*30)+i*4)))}/>
          <div style={{fontSize:11,color:"var(--text-mid)",marginTop:8}}>Northeast Monsoon peak (Oct-Dec) dominates. 2015 &amp; 2023 seasons show extreme November signatures — pattern the AI recognizes.</div>
        </div>
      </div>

      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd"><h3>Climate-Change Indicators</h3><span className="sub">Tamil Nadu · derived signals</span></div>
        <div className="panel-bd" style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:12}}>
          {[
            ["Extreme Rain Events","+38%","last decade","#EF4444"],
            ["Dry-spell Length","+22%","longer between rains","#F97316"],
            ["Coastal SST","+0.9°C","above 20-yr baseline","#F59E0B"],
            ["Cyclone Landfalls","2.1×","frequency vs 2000s","#A78BFA"],
          ].map(([k,v,s,c],i)=>(
            <div key={i} style={{padding:14,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:12,borderLeft:`3px solid ${c}`}}>
              <div className="k">{k}</div>
              <div style={{fontSize:26,fontWeight:700,color:c,letterSpacing:"-0.02em",marginTop:4}} className="num">{v}</div>
              <div style={{fontSize:11.5,color:"var(--text-mid)",marginTop:2}}>{s}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function AdminScreen(){
  const [models, setModels] = useState_cha(null);
  const [modelsErr, setModelsErr] = useState_cha(null);
  useEffect_cha(() => {
    let alive = true;
    if (!window.RIIS_API) return;
    (window.RIIS_API.ready || Promise.resolve())
      .then(() => window.RIIS_API.getModels())
      .then(r => { if (alive) setModels(r); })
      .catch(e => { if (alive) setModelsErr(String(e.message || e)); });
    return () => { alive = false; };
  }, []);
  const modelRows = models ? modelRowsFromRegistry(models) : null;
  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">SYSTEM <b>Admin Dashboard</b></div>
          <h1 style={{marginTop:6}}>Platform &amp; Model Operations</h1>
          <p style={{marginTop:4}}>Sensor uptime, model accuracy, alert throughput, retraining status · full system observability</p>
        </div>
        <div className="id">RIIS-OPS · ROOT SCOPE</div>
      </div>

      {/* System health strip */}
      <div style={{display:"grid",gridTemplateColumns:"repeat(6,1fr)",gap:12,marginBottom:16}}>
        {[
          ["AWS Network","47 / 47","#10B981","100% uptime"],
          ["ARG Network","110 / 112","#F59E0B","2 offline"],
          ["Doppler Radar","1 / 1","#10B981","nominal"],
          ["INSAT-3DR","LIVE","#10B981","+3 img/30m"],
          ["Reservoirs","14 / 14","#10B981","SCADA OK"],
          ["Rivers Gauged","28 / 30","#F59E0B","2 lagging"]
        ].map(([k,v,c,s],i)=>(
          <div key={i} className="panel" style={{padding:14,borderTop:`2px solid ${c}`}}>
            <div className="k">{k}</div>
            <div style={{fontSize:20,fontWeight:700,color:c,marginTop:2}} className="num">{v}</div>
            <div style={{fontSize:11,color:"var(--text-mid)",marginTop:2}}>{s}</div>
          </div>
        ))}
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1.4fr 1fr",gap:16}}>
        <div className="panel brackets">
          <div className="panel-hd"><h3>Model Performance</h3>
            <span className="live"><span className="d"/>{modelRows ? `${modelRows.length} TRAINED` : modelsErr ? "OFFLINE" : "LOADING"}</span>
            <span className="sub">{modelRows ? "held-out test metrics · ml_models/model_registry.json" : modelsErr ? `backend unreachable (${modelsErr})` : "fetching /api/ml/models"}</span></div>
          <div className="panel-bd">
            <table className="data">
              <thead><tr><th>Model</th><th>Family</th><th>Target</th><th>Accuracy / RMSE</th><th>Macro F1 / CSI</th><th>Heavy-rain AUC / baseline</th><th>Train rows</th><th>Train time</th><th>Trained</th></tr></thead>
              <tbody>
                {(modelRows || []).map((r,i)=>(
                  <tr key={r.key} style={{background:r.key==="ensemble_vote"?"rgba(34,211,238,0.05)":undefined}}>
                    <td style={{fontWeight:r.key==="ensemble_vote"?700:500}}>{r.name}</td>
                    <td className="mono" style={{color:"var(--text-mid)"}}>{r.family}</td>
                    <td style={{color:"var(--text-mid)",fontSize:11}}>{r.task}</td>
                    <td className="mono" style={{color:r.primaryPct==null?"#7DD3FC":r.primaryPct>85?"#5EEAD4":r.primaryPct>70?"#FCD34D":"#FCA5A5",fontWeight:600}}>{r.primary}</td>
                    <td className="mono">{r.secondary}</td>
                    <td className="mono">{r.tertiary}</td>
                    <td className="mono" style={{color:"var(--text-mid)"}}>{r.rows}</td>
                    <td className="mono" style={{color:"var(--text-mid)"}}>{r.secs}</td>
                    <td className="mono" style={{color:"var(--text-lo)"}}>{r.trained}</td>
                  </tr>
                ))}
                {!modelRows && (
                  <tr><td colSpan={9} style={{color:"var(--text-lo)",fontSize:12,padding:"12px 8px"}}>
                    {modelsErr ? "Start the backend (start-riis.ps1) to load the trained model registry." : "Loading trained models…"}
                  </td></tr>
                )}
              </tbody>
            </table>
            {modelRows && (
              <div style={{fontSize:10.5,color:"var(--text-lo)",marginTop:8,lineHeight:1.5}}>
                Tabular models predict tomorrow's rain class from today's weather and 30 days of history; sequence models predict the next 6 hours from 48 hourly steps;
                spatial models predict a 6-hour rain map on an 11×11 grid, compared against persistence. Chronological hold-out, no leakage.
              </div>
            )}
          </div>
        </div>

        <div className="vstack" style={{gap:16}}>
          <div className="panel brackets">
            <div className="panel-hd"><h3>Alert Throughput</h3><span className="sub">Last 24 h</span></div>
            <div className="panel-bd">
              <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:8}}>
                {[
                  ["Sent","24,182","#22D3EE"],
                  ["Delivered","23,940","#10B981"],
                  ["Read","19,884","#7DD3FC"],
                  ["Acted","4,412","#A78BFA"],
                  ["Failed","242","#EF4444"],
                  ["Retried","238","#F59E0B"]
                ].map(([k,v,c],i)=>(
                  <div key={i} style={{padding:10,background:"rgba(10,18,28,0.5)",border:"1px solid var(--stroke)",borderRadius:8,textAlign:"center"}}>
                    <div style={{fontSize:18,fontWeight:700,color:c,letterSpacing:"-0.02em"}} className="num">{v}</div>
                    <div className="k" style={{marginTop:2}}>{k}</div>
                  </div>
                ))}
              </div>
              <div style={{marginTop:12}}>
                <Sparkline data={[820,940,1120,1440,2100,2820,3210,2410,1820,1440,1120,940]} w={340} h={60} color="#22D3EE"/>
                <div className="k" style={{marginTop:4}}>SMS + PUSH + WA · alerts/hour</div>
              </div>
            </div>
          </div>
          <div className="panel brackets">
            <div className="panel-hd"><h3>Retraining Queue</h3></div>
            <div className="panel-bd">
              {[
                ["ConvLSTM v4.3","running","46%","4h 12m",  "#22D3EE"],
                ["XGBoost-Ens v2.0","queued", "—",    "~2h",   "#F59E0B"],
                ["CNN-Nowcast v5.2","queued", "—",    "~3h",   "#F59E0B"],
                ["Ensemble weights","queued","—",     "~30m",  "#7DD3FC"],
              ].map(([n,st,pct,eta,c],i)=>(
                <div key={i} style={{padding:"10px 8px",borderBottom:i<3?"1px solid var(--stroke)":"none"}}>
                  <div style={{display:"flex",justifyContent:"space-between",fontSize:12,fontWeight:500}}><span>{n}</span><span className="mono" style={{color:c}}>{st.toUpperCase()}</span></div>
                  <div style={{display:"flex",alignItems:"center",gap:8,marginTop:6}}>
                    <div style={{flex:1,height:5,background:"rgba(20,32,48,0.7)",borderRadius:3,overflow:"hidden"}}><div style={{width:pct==="—"?"0%":pct,height:"100%",background:c,transition:"width .4s"}}/></div>
                    <span className="mono" style={{fontSize:10,color:"var(--text-lo)"}}>ETA {eta}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* System logs */}
      <div className="panel brackets" style={{marginTop:16}}>
        <div className="panel-hd"><h3>System Logs</h3><span className="live"><span className="d"/>STREAMING</span></div>
        <div className="panel-bd" style={{padding:"0"}}>
          <div style={{padding:14,background:"rgba(5,9,15,0.6)",fontFamily:"JetBrains Mono, monospace",fontSize:11.5,lineHeight:1.8,maxHeight:280,overflowY:"auto"}}>
            {[
              ["INFO","14:32:18","inference","ConvLSTM-v4.2 · Chennai grid · rain_6h=84.5mm · conf=0.96 · 842ms"],
              ["INFO","14:32:12","ingest","INSAT-3DR frame received · cloud_top=−68C · lag=612ms"],
              ["INFO","14:32:03","ingest","Doppler radar sweep completed · 480 azimuths · max_dBZ=52"],
              ["WARN","14:31:58","aws","AWS-CHN-14 (Marina) latency 4.2s — investigating"],
              ["INFO","14:31:44","alert","Alert dispatched · 4,182 recipients · Chennai zone · ack rate 87%"],
              ["INFO","14:31:22","impact","impact engine · risk_index=82 · class=EXTREME · vectors=9"],
              ["INFO","14:31:04","reservoir","Chembarambakkam SCADA · fill=88% · gate rec=2×1.5m"],
              ["ERR ","14:30:52","arg","ARG-VLL-03 timeout · fallback to interpolated ERA5"],
              ["INFO","14:30:40","community","report ingested · @arun_ch · Velachery · 0.6m · verified=true"],
              ["INFO","14:30:22","retrain","Nightly retrain scheduled 02:00 IST · +412 new samples"],
              ["INFO","14:30:04","xai","SHAP explanation cached · features=9 · latency=142ms"],
            ].map((r,i)=>{
              const cc = r[0]==="ERR "?"#FCA5A5":r[0]==="WARN"?"#FCD34D":"var(--text-lo)";
              return (
                <div key={i} style={{display:"flex",gap:14,color:"var(--text-mid)"}}>
                  <span style={{color:cc,fontWeight:600,width:38}}>{r[0]}</span>
                  <span style={{color:"var(--text-lo)",width:64}}>{r[1]}</span>
                  <span style={{color:"var(--cyan)",width:96}}>{r[2]}</span>
                  <span style={{color:"var(--text-hi)"}}>{r[3]}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

window.CommunityScreen = CommunityScreen;
window.HistoryScreen = HistoryScreen;
window.AdminScreen = AdminScreen;
