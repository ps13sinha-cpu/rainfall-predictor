// RIIS — Safe Routes: flood-aware routing on the real OSM road network
const { useState: useState_r, useEffect: useEffect_r, useRef: useRef_r } = React;

const ROUTE_STATUS_COLOR = { open: '#10B981', caution: '#F59E0B', closed_cars: '#EF4444', closed_all: '#7F1D1D' };
const ROUTE_STATUS_LABEL = { open: 'Open', caution: 'Caution', closed_cars: 'Closed to cars', closed_all: 'Closed to all' };

function readRouteParams() {
  const q = (location.hash.split('?')[1] || '');
  const p = new URLSearchParams(q);
  const pt = s => { if (!s) return null; const [a, b] = s.split(',').map(Number); return isFinite(a) && isFinite(b) ? { lat: a, lon: b } : null; };
  return { from: pt(p.get('from')), to: pt(p.get('to')), rain: p.get('rain') ? +p.get('rain') : null, dur: p.get('dur') ? +p.get('dur') : null, mode: p.get('mode') };
}

function RoutesScreen() {
  const params = readRouteParams();
  const liveRain = Math.max(10, Math.round((RIIS.prediction && RIIS.prediction.rainfall_mm) || 0) || 40);
  const [origin, setOrigin] = useState_r(() => params.from || (RIIS.location.lat != null ? { lat: RIIS.location.lat, lon: RIIS.location.lon } : null));
  const [dest, setDest] = useState_r(() => params.to);
  const [originLabel, setOriginLabel] = useState_r(params.from ? '' : 'Your location');
  const [destLabel, setDestLabel] = useState_r('');
  const [mode, setMode] = useState_r(params.mode && ['car', 'bike', 'walk'].includes(params.mode) ? params.mode : 'car');
  const [rain, setRain] = useState_r(params.rain || liveRain);
  const [dur, setDur] = useState_r(params.dur || 3);
  const [query, setQuery] = useState_r('');
  const [results, setResults] = useState_r([]);
  const [picking, setPicking] = useState_r(null);
  const [roads, setRoads] = useState_r(null);
  const [roadsState, setRoadsState] = useState_r('idle');
  const [routes, setRoutes] = useState_r(null);
  const [routeState, setRouteState] = useState_r('idle');
  const [routeErr, setRouteErr] = useState_r(null);
  const [reports, setReports] = useState_r([]);
  const [model, setModel] = useState_r(null);
  const [flashId, setFlashId] = useState_r(null);
  const [copied, setCopied] = useState_r(false);
  const [toast, setToast] = useState_r(null);
  const [retryTick, setRetryTick] = useState_r(0);
  const scenario = { rainfall_mm: rain, duration_h: dur };

  // Model metrics once
  useEffect_r(() => {
    if (!window.RIIS_API) return;
    (window.RIIS_API.ready || Promise.resolve()).then(() => window.RIIS_API.getRoadModel()).then(setModel).catch(() => {});
  }, []);

  // Reverse-geocode labels
  useEffect_r(() => {
    if (!window.RIIS_API || !origin) return;
    let alive = true;
    window.RIIS_API.reverseGeocode(origin.lat, origin.lon).then(r => { if (alive) setOriginLabel(r.short || r.name || `${origin.lat.toFixed(4)}, ${origin.lon.toFixed(4)}`); }).catch(() => {});
    return () => { alive = false; };
  }, [origin && origin.lat, origin && origin.lon]);
  useEffect_r(() => {
    if (!window.RIIS_API || !dest) return;
    let alive = true;
    if (!destLabel) window.RIIS_API.reverseGeocode(dest.lat, dest.lon).then(r => { if (alive) setDestLabel(r.short || r.name || `${dest.lat.toFixed(4)}, ${dest.lon.toFixed(4)}`); }).catch(() => {});
    return () => { alive = false; };
  }, [dest && dest.lat, dest && dest.lon]);

  // Destination search (400 ms debounce)
  useEffect_r(() => {
    if (!window.RIIS_API || !origin || query.trim().length < 2) { setResults([]); return; }
    let alive = true;
    const t = setTimeout(() => {
      window.RIIS_API.geocode(query.trim(), origin.lat, origin.lon).then(r => { if (alive) setResults(r.results || []); }).catch(() => { if (alive) setResults([]); });
    }, 400);
    return () => { alive = false; clearTimeout(t); };
  }, [query]);

  // Roads for the scenario (500 ms debounce)
  useEffect_r(() => {
    if (!window.RIIS_API || !origin) return;
    let alive = true;
    setRoadsState('loading');
    const t = setTimeout(() => {
      (window.RIIS_API.ready || Promise.resolve()).then(() => Promise.all([
        window.RIIS_API.getRoads({ lat: origin.lat, lon: origin.lon, rainfall_mm: rain, duration_h: dur, mode }),
        window.RIIS_API.getRoadReports(origin.lat, origin.lon).catch(() => ({ reports: [] })),
      ])).then(([r, rep]) => { if (!alive) return; setRoads(r); setReports(rep.reports || []); setRoadsState('ok'); })
        .catch(e => { if (alive) { console.warn('[RIIS] roads failed', e.message); setRoadsState('error'); } });
    }, 500);
    return () => { alive = false; clearTimeout(t); };
  }, [origin && origin.lat, origin && origin.lon, rain, dur, mode, retryTick]);

  // Route when both points are set (500 ms debounce)
  useEffect_r(() => {
    if (!window.RIIS_API || !origin || !dest) { setRoutes(null); return; }
    let alive = true;
    setRouteState('loading'); setRouteErr(null);
    const t = setTimeout(() => {
      window.RIIS_API.getRoute({ from_lat: origin.lat, from_lon: origin.lon, to_lat: dest.lat, to_lon: dest.lon, rainfall_mm: rain, duration_h: dur, mode })
        .then(r => { if (!alive) return; setRoutes(r); setRouteState('ok'); if (r.error) setRouteErr(r.error); })
        .catch(e => { if (alive) { setRouteState('error'); setRouteErr(e.message); } });
    }, 500);
    return () => { alive = false; clearTimeout(t); };
  }, [origin && origin.lat, origin && origin.lon, dest && dest.lat, dest && dest.lon, rain, dur, mode, retryTick]);

  const pick = (which, pt) => { if (which === 'origin') setOrigin(pt); else { setDest(pt); setDestLabel(''); } setPicking(null); };
  const useLive = () => { setRain(liveRain); setDur(3); };
  const share = () => {
    const url = `${location.origin}${location.pathname}#/routes?from=${origin.lat.toFixed(5)},${origin.lon.toFixed(5)}${dest ? `&to=${dest.lat.toFixed(5)},${dest.lon.toFixed(5)}` : ''}&rain=${rain}&dur=${dur}&mode=${mode}`;
    (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => prompt('Copy this link', url));
  };
  const report = body => {
    window.RIIS_API.postRoadReport({ lat: body.lat, lon: body.lon, status: body.status, depth_cm: body.depth_cm, note: body.note, rainfall_mm: rain, duration_h: dur })
      .then(() => { setToast('Report saved — roads and route refreshed'); setRetryTick(t => t + 1); setTimeout(() => setToast(null), 2500); })
      .catch(e => { setToast(`Report failed: ${e.message}`); setTimeout(() => setToast(null), 3000); });
  };

  const safe = routes && routes.safe_route, normal = routes && routes.normal_route;
  const diffM = safe && normal ? safe.length_m - normal.length_m : null;
  const most = roads ? roads.most_affected || [] : [];
  const fmtKm = m => m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
  const ctrl = { padding: '10px 12px', background: 'rgba(10,18,28,0.5)', border: '1px solid var(--stroke)', borderRadius: 8 };
  const input = { width: '100%', background: 'var(--bg-1)', border: '1px solid var(--stroke-2)', borderRadius: 6, color: 'var(--text-hi)', padding: '7px 9px', fontSize: 12.5, fontFamily: 'inherit' };

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">MOBILITY <b>Safe Routes</b></div>
          <h1 style={{ marginTop: 6 }}>Flood-aware routing — {RIIS.location.city || 'Local Area'}</h1>
          <p style={{ marginTop: 4 }}>Every road segment within ~3.6 km is scored against the DEM ponding model for the chosen rainfall; the safe route avoids closed roads and penalises cautious ones.</p>
        </div>
        <div className="id">OSM ROADS · SRTM DEM · {roads ? `${roads.features.length} SEGMENTS` : 'LOADING'}</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2fr) minmax(300px,1fr)', gap: 16 }} className="routes-grid">
        <div className="panel brackets">
          <div className="panel-hd">
            <h3>Road network · flood status</h3>
            <span className="live" style={{ background: 'rgba(34,211,238,0.12)', color: 'var(--cyan)' }}><span className="d" style={{ background: 'var(--cyan)' }} />{rain} mm / {dur} h · {mode.toUpperCase()}</span>
            <span className="sub">{roads ? `site ${roads.site.id} · DEM ${roads.site.dem_res_m} m · computed in ${roads.computed_in_s}s` : 'DEM + OSM + ponding'}</span>
          </div>
          <div className="panel-bd">
            <SafeRouteMap origin={origin} dest={dest} scenario={scenario} mode={mode} roads={roads} routes={routes} reports={reports}
              picking={picking} flashSegmentId={flashId} state={roadsState} onPick={pick}
              onMoveOrigin={pt => setOrigin(pt)} onMoveDest={pt => { setDest(pt); setDestLabel(''); }} onReport={report}
              onRetry={() => setRetryTick(t => t + 1)} />
            {toast && <div style={{ marginTop: 8, fontSize: 12, color: 'var(--cyan)' }}>{toast}</div>}
          </div>
        </div>

        <div className="vstack" style={{ gap: 16 }}>
          <div className="panel brackets">
            <div className="panel-hd"><h3>Plan</h3><span className="sub">origin · destination · mode · scenario</span></div>
            <div className="panel-bd" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={ctrl}>
                <div className="k" style={{ display: 'flex', justifyContent: 'space-between' }}><span>ORIGIN</span>
                  <span style={{ display: 'flex', gap: 6 }}>
                    <button className={'chip ' + (picking === 'origin' ? 'active' : '')} onClick={() => setPicking(picking === 'origin' ? null : 'origin')}>Pick on map</button>
                    <button className="chip" onClick={() => { setOrigin({ lat: RIIS.location.lat, lon: RIIS.location.lon }); setOriginLabel('Your location'); }}>Your location</button>
                  </span></div>
                <div style={{ fontSize: 12.5, marginTop: 4, color: 'var(--text-hi)' }}>{origin ? (originLabel || `${origin.lat.toFixed(4)}, ${origin.lon.toFixed(4)}`) : 'Not set'}</div>
              </div>
              <div style={ctrl}>
                <div className="k" style={{ display: 'flex', justifyContent: 'space-between' }}><span>DESTINATION</span>
                  <button className={'chip ' + (picking === 'dest' ? 'active' : '')} onClick={() => setPicking(picking === 'dest' ? null : 'dest')}>Pick on map</button></div>
                <input style={{ ...input, marginTop: 6 }} placeholder="Search a place within 15 km…" value={query} onChange={e => setQuery(e.target.value)} />
                {results.length > 0 && (
                  <div style={{ marginTop: 4, border: '1px solid var(--stroke)', borderRadius: 6, overflow: 'hidden' }}>
                    {results.map((r, i) => (
                      <div key={i} onClick={() => { setDest({ lat: r.lat, lon: r.lon }); setDestLabel(r.name.split(',').slice(0, 2).join(',')); setQuery(''); setResults([]); }}
                        style={{ padding: '6px 8px', fontSize: 12, cursor: 'pointer', borderBottom: '1px solid var(--stroke)', background: 'rgba(10,18,28,0.6)' }}>
                        {r.name.split(',').slice(0, 3).join(',')} <span className="mono" style={{ color: 'var(--text-lo)' }}>· {r.distance_km} km</span>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ fontSize: 12.5, marginTop: 6, color: 'var(--text-hi)' }}>{dest ? (destLabel || `${dest.lat.toFixed(4)}, ${dest.lon.toFixed(4)}`) : 'Search or pick on the map'}</div>
              </div>
              <div style={ctrl}>
                <div className="k">MODE</div>
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  {[['car', 'Car'], ['bike', 'Bike'], ['walk', 'Walk']].map(([v, l]) => <button key={v} className={'chip ' + (mode === v ? 'active' : '')} onClick={() => setMode(v)}>{l}</button>)}
                </div>
              </div>
              <div style={ctrl}>
                <div className="k" style={{ display: 'flex', justifyContent: 'space-between' }}><span>SCENARIO</span><button className="chip" onClick={useLive}>Use live forecast ({liveRain} mm)</button></div>
                <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr 54px', gap: 8, alignItems: 'center', marginTop: 8, fontSize: 12 }}>
                  <span>Rainfall</span><input className="sim" type="range" min="0" max="300" step="5" value={rain} onChange={e => setRain(+e.target.value)} /><span className="mono" style={{ textAlign: 'right' }}>{rain} mm</span>
                  <span>Duration</span><input className="sim" type="range" min="1" max="24" step="1" value={dur} onChange={e => setDur(+e.target.value)} /><span className="mono" style={{ textAlign: 'right' }}>{dur} h</span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn primary" disabled={!origin || !dest} onClick={() => setRetryTick(t => t + 1)} style={{ flex: 1 }}>{routeState === 'loading' ? 'Routing…' : 'Find safe route'}</button>
                <button className="btn ghost" disabled={!origin} onClick={share}>{copied ? 'Copied' : 'Share'}</button>
              </div>
            </div>
          </div>

          <div className="panel brackets">
            <div className="panel-hd"><h3>Route comparison</h3>{routes && <span className="sub">{routes.reachable ? 'safe route found' : 'no safe route'}</span>}</div>
            <div className="panel-bd">
              {!dest && <div style={{ fontSize: 12.5, color: 'var(--text-lo)' }}>Set a destination to compare the safe and normal routes.</div>}
              {dest && routeState === 'loading' && !routes && <div style={{ fontSize: 12.5, color: 'var(--text-lo)' }}>Computing…</div>}
              {routeErr && <div style={{ fontSize: 12, color: '#FCA5A5', marginBottom: 8 }}>{routeErr}</div>}
              {routes && routes.snapped === false && !routeErr && <div style={{ fontSize: 12, color: '#FCA5A5' }}>Could not snap to the road network.</div>}
              {routes && routes.reachable === false && routes.snapped && (
                <div style={{ padding: '8px 10px', background: 'rgba(239,68,68,0.12)', border: '1px solid #EF444455', borderRadius: 8, marginBottom: 10, fontSize: 12 }}>
                  <b style={{ color: '#FCA5A5' }}>Destination cut off under this scenario.</b>
                  {(routes.blocking_segments || []).length > 0 && <div style={{ color: 'var(--text-mid)', marginTop: 4 }}>Blocked by: {routes.blocking_segments.slice(0, 5).map(s => `${s.name || s.highway} (${s.max_depth_m} m)`).join(', ')}</div>}
                </div>
              )}
              {routes && (safe || normal) && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {[['Safe', safe, '#22D3EE'], ['Normal', normal, '#94A3B8']].map(([lbl, r, c]) => r && (
                    <div key={lbl} style={{ display: 'grid', gridTemplateColumns: '60px 1fr 1fr 1fr', gap: 8, alignItems: 'center', padding: '8px 10px', background: 'rgba(10,18,28,0.5)', border: `1px solid ${c}44`, borderLeft: `3px solid ${c}`, borderRadius: 8, fontSize: 12 }}>
                      <b style={{ color: c }}>{lbl}</b>
                      <span><span className="k">DIST</span><br /><span className="mono">{fmtKm(r.length_m)}</span></span>
                      <span><span className="k">ETA</span><br /><span className="mono">{r.eta_min} min</span></span>
                      <span><span className="k">WORST</span><br /><span className="mono" style={{ color: ROUTE_STATUS_COLOR[r.worst_status] }}>{ROUTE_STATUS_LABEL[r.worst_status]}{r.closed_segments ? ` · ${r.closed_segments} closed` : ''}</span></span>
                    </div>
                  ))}
                  {safe && normal && (
                    <div style={{ fontSize: 12, color: 'var(--text-hi)' }}>
                      {diffM > 0 ? `+${fmtKm(diffM)} (${(safe.eta_min - normal.eta_min).toFixed(1)} min)` : 'Same length'} · avoids {routes.closed_avoided.length} flooded segment{routes.closed_avoided.length === 1 ? '' : 's'}
                      {routes.closed_avoided.length > 0 && <span style={{ color: 'var(--text-mid)' }}> · {routes.closed_avoided.slice(0, 3).map(s => `${s.name || 'unnamed'} ${s.max_depth_m} m`).join(', ')}</span>}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="panel brackets">
            <div className="panel-hd"><h3>Most affected roads</h3><span className="sub">{most.length} named roads</span></div>
            <div className="panel-bd" style={{ maxHeight: 260, overflowY: 'auto' }}>
              {roadsState === 'loading' && !roads && <div style={{ fontSize: 12.5, color: 'var(--text-lo)' }}>Scoring the road network…</div>}
              {roads && most.length === 0 && <div style={{ fontSize: 12.5, color: 'var(--text-lo)' }}>No road is affected at {rain} mm / {dur} h.</div>}
              {most.map((r, i) => (
                <div key={i} onClick={() => setFlashId(r.segment_id)} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 8, alignItems: 'center', padding: '6px 0', borderBottom: '1px dashed rgba(120,180,255,0.08)', cursor: 'pointer', fontSize: 12 }}>
                  <span><b style={{ color: 'var(--text-hi)' }}>{r.name}</b> <span style={{ color: 'var(--text-lo)' }}>{r.highway}</span></span>
                  <span className="mono" style={{ color: 'var(--text-mid)' }}>{r.max_depth_m} m</span>
                  <span className="sev" style={{ color: ROUTE_STATUS_COLOR[r.status], background: ROUTE_STATUS_COLOR[r.status] + '22', fontSize: 10 }}>{ROUTE_STATUS_LABEL[r.status]}</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ fontSize: 10.5, color: 'var(--text-lo)', lineHeight: 1.5, padding: '0 4px' }}>
            Model: {model && model.macro_f1 != null
              ? `road risk surrogate · macro F1 ${model.macro_f1} on held-out site ${model.held_out_site} · ${model.label_sources.sim.toLocaleString()} simulated + ${model.label_sources.report} community labels`
              : 'road risk surrogate not trained yet (run python -m app.train_roads)'}
            {roads && roads.risk_ml_coverage != null && ` · risk_ml on ${Math.round(roads.risk_ml_coverage * 100)}% of segments`}.
            Statuses come from the DEM ponding simulation unless a community report within 25 m overrides them.
          </div>
        </div>
      </div>
      <style>{`@media (max-width: 900px) { .routes-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}

window.RoutesScreen = RoutesScreen;
