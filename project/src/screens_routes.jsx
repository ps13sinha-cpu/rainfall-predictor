// RIIS — Safe Routes: flood-aware routing on the real OSM road network, driven by LIVE rain
// (rain observed in the last 6 h + the next 6 h forecast at the origin). No what-if sliders here;
// use the Flood Simulator for scenarios.
const { useState: useState_r, useEffect: useEffect_r } = React;

const ROUTE_STATUS_COLOR = { open: '#10B981', caution: '#F59E0B', closed_cars: '#EF4444', closed_all: '#7F1D1D' };
const ROUTE_STATUS_LABEL = { open: 'Open', caution: 'Caution', closed_cars: 'Closed to cars', closed_all: 'Closed to all' };
const LIVE_REFRESH_MS = 10 * 60 * 1000;

function readRouteParams() {
  const p = new URLSearchParams(location.hash.split('?')[1] || '');
  const pt = s => { if (!s) return null; const [a, b] = s.split(',').map(Number); return isFinite(a) && isFinite(b) ? { lat: a, lon: b } : null; };
  return { from: pt(p.get('from')), to: pt(p.get('to')), mode: p.get('mode') };
}

function RoutesScreen() {
  const params = readRouteParams();
  const [origin, setOrigin] = useState_r(() => params.from || (RIIS.location.lat != null ? { lat: RIIS.location.lat, lon: RIIS.location.lon } : null));
  const [dest, setDest] = useState_r(() => params.to);
  const [originLabel, setOriginLabel] = useState_r(params.from ? '' : 'Your location');
  const [destLabel, setDestLabel] = useState_r('');
  const [mode, setMode] = useState_r(params.mode && ['car', 'bike', 'walk'].includes(params.mode) ? params.mode : 'car');
  const [query, setQuery] = useState_r('');
  const [results, setResults] = useState_r([]);
  const [picking, setPicking] = useState_r(null);
  const [roads, setRoads] = useState_r(null);
  const [roadsState, setRoadsState] = useState_r('idle');
  const [roadsErr, setRoadsErr] = useState_r(null);
  const [routes, setRoutes] = useState_r(null);
  const [routeState, setRouteState] = useState_r('idle');
  const [routeErr, setRouteErr] = useState_r(null);
  const [reports, setReports] = useState_r([]);
  const [model, setModel] = useState_r(null);
  const [flashId, setFlashId] = useState_r(null);
  const [copied, setCopied] = useState_r(false);
  const [toast, setToast] = useState_r(null);
  const [tick, setTick] = useState_r(0);
  const live = roads && roads.scenario ? roads.scenario : null;   // live rain the roads were scored with
  const scenario = live ? { rainfall_mm: live.rainfall_mm, duration_h: live.duration_h } : { rainfall_mm: 0, duration_h: 12 };

  // Refresh live conditions every 10 minutes
  useEffect_r(() => { const iv = setInterval(() => setTick(t => t + 1), LIVE_REFRESH_MS); return () => clearInterval(iv); }, []);

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

  // Roads scored with live rain (no rainfall_mm param => backend uses observed + forecast)
  useEffect_r(() => {
    if (!window.RIIS_API || !origin) return;
    let alive = true;
    setRoadsState('loading'); setRoadsErr(null);
    const t = setTimeout(() => {
      (window.RIIS_API.ready || Promise.resolve()).then(() => Promise.all([
        window.RIIS_API.getRoads({ lat: origin.lat, lon: origin.lon, mode }),
        window.RIIS_API.getRoadReports(origin.lat, origin.lon).catch(() => ({ reports: [] })),
      ])).then(([r, rep]) => { if (!alive) return; setRoads(r); setReports(rep.reports || []); setRoadsState('ok'); })
        .catch(e => { if (alive) { console.warn('[RIIS] roads failed', e.message); setRoadsErr(e.message); setRoadsState('error'); } });
    }, 300);
    return () => { alive = false; clearTimeout(t); };
  }, [origin && origin.lat, origin && origin.lon, mode, tick]);

  // Safe route when both points are set
  useEffect_r(() => {
    if (!window.RIIS_API || !origin || !dest) { setRoutes(null); return; }
    let alive = true;
    setRouteState('loading'); setRouteErr(null);
    const t = setTimeout(() => {
      window.RIIS_API.getRoute({ from_lat: origin.lat, from_lon: origin.lon, to_lat: dest.lat, to_lon: dest.lon, mode })
        .then(r => { if (!alive) return; setRoutes(r); setRouteState('ok'); if (r.error) setRouteErr(r.error); })
        .catch(e => { if (alive) { setRouteState('error'); setRouteErr(e.message); } });
    }, 400);
    return () => { alive = false; clearTimeout(t); };
  }, [origin && origin.lat, origin && origin.lon, dest && dest.lat, dest && dest.lon, mode, tick]);

  const pick = (which, pt) => { if (which === 'origin') setOrigin(pt); else { setDest(pt); setDestLabel(''); } setPicking(null); };
  const share = () => {
    const url = `${location.origin}${location.pathname}#/routes?from=${origin.lat.toFixed(5)},${origin.lon.toFixed(5)}${dest ? `&to=${dest.lat.toFixed(5)},${dest.lon.toFixed(5)}` : ''}&mode=${mode}`;
    (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => prompt('Copy this link', url));
  };
  const report = body => {
    window.RIIS_API.postRoadReport({ lat: body.lat, lon: body.lon, status: body.status, depth_cm: body.depth_cm, note: body.note,
      rainfall_mm: live ? live.rainfall_mm : null, duration_h: live ? live.duration_h : null })
      .then(() => { setToast('Report saved — roads and route refreshed'); setTick(t => t + 1); setTimeout(() => setToast(null), 2500); })
      .catch(e => { setToast(`Report failed: ${e.message}`); setTimeout(() => setToast(null), 3000); });
  };

  const safe = routes && routes.safe_route, normal = routes && routes.normal_route;
  const most = roads ? roads.most_affected || [] : [];
  const counts = roads ? roads.status_counts || {} : {};
  const nClosed = (counts.closed_cars || 0) + (counts.closed_all || 0);
  const raining = live && (live.current_mm_h > 0 || live.past_6h_mm > 0.5 || live.next_6h_mm > 0.5);
  const fmtKm = m => m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${Math.round(m)} m`;
  const ctrl = { padding: '10px 12px', background: 'rgba(10,18,28,0.5)', border: '1px solid var(--stroke)', borderRadius: 8 };
  const input = { width: '100%', background: 'var(--bg-1)', border: '1px solid var(--stroke-2)', borderRadius: 6, color: 'var(--text-hi)', padding: '7px 9px', fontSize: 12.5, fontFamily: 'inherit' };
  const liveColor = !live ? 'var(--text-lo)' : nClosed ? '#EF4444' : (counts.caution ? '#F59E0B' : '#10B981');

  return (
    <div className="screen">
      <div className="screen-title">
        <div>
          <div className="crumb">MOBILITY <b>Safe Routes</b></div>
          <h1 style={{ marginTop: 6 }}>Safe routes right now — {RIIS.location.city || 'Local Area'}</h1>
          <p style={{ marginTop: 4 }}>Roads within ~3.6 km are scored against the rain that has fallen in the last 6 hours and the next 6 hours of forecast at your origin. The route shown avoids closed roads and steers around cautious ones.</p>
        </div>
        <div className="id">LIVE RAIN · OSM ROADS · SRTM DEM</div>
      </div>

      {/* Live conditions strip */}
      <div className="panel" style={{ display: 'flex', alignItems: 'center', gap: 18, padding: '10px 14px', marginBottom: 14, borderLeft: `3px solid ${liveColor}`, flexWrap: 'wrap' }}>
        <div>
          <div className="k">LIVE CONDITIONS</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: liveColor, marginTop: 2 }}>
            {!live ? (roadsState === 'error' ? 'Backend unreachable' : 'Reading rain at your location…')
              : raining ? `Rain in progress · ${live.rainfall_mm} mm over 12 h (past 6 h ${live.past_6h_mm} mm · next 6 h ${live.next_6h_mm} mm)`
              : `Dry right now · ${live.next_6h_mm} mm expected in the next 6 h`}
          </div>
        </div>
        {live && [
          ['Now', `${live.current_mm_h} mm/h`], ['Past 6 h', `${live.past_6h_mm} mm`], ['Next 6 h', `${live.next_6h_mm} mm`],
          ['Last 7 days', `${live.rain_7d_mm != null ? live.rain_7d_mm : '—'} mm`], ['Soil saturation', `${live.saturation_pct != null ? live.saturation_pct : '—'}%`],
          ['Roads', `${counts.open || 0} open · ${counts.caution || 0} caution · ${nClosed} closed`],
        ].map(([k, v], i) => (
          <div key={i}><div className="k">{k}</div><div className="mono" style={{ fontSize: 12.5, color: 'var(--text-hi)' }}>{v}</div></div>
        ))}
        <button className="btn ghost" style={{ marginLeft: 'auto' }} onClick={() => setTick(t => t + 1)}>Refresh</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2fr) minmax(300px,1fr)', gap: 16 }} className="routes-grid">
        <div className="panel brackets">
          <div className="panel-hd">
            <h3>Road network · current flood status</h3>
            <span className="live" style={{ background: liveColor + '22', color: liveColor }}><span className="d" style={{ background: liveColor }} />{live ? `${live.rainfall_mm} mm LIVE · ${mode.toUpperCase()}` : 'LIVE'}</span>
            <span className="sub">{roads ? `${roads.features.length} segments · DEM ${roads.site.dem_res_m} m · ${roads.computed_in_s}s` : 'DEM + OSM + live rain'}</span>
          </div>
          <div className="panel-bd">
            <SafeRouteMap origin={origin} dest={dest} scenario={scenario} mode={mode} roads={roads} routes={routes} reports={reports}
              picking={picking} flashSegmentId={flashId} state={roadsState} errorText={roadsErr} showNormal={false} onPick={pick}
              onMoveOrigin={pt => setOrigin(pt)} onMoveDest={pt => { setDest(pt); setDestLabel(''); }} onReport={report}
              onRetry={() => setTick(t => t + 1)} />
            {toast && <div style={{ marginTop: 8, fontSize: 12, color: 'var(--cyan)' }}>{toast}</div>}
          </div>
        </div>

        <div className="vstack" style={{ gap: 16 }}>
          <div className="panel brackets">
            <div className="panel-hd"><h3>Where to?</h3><span className="sub">origin · destination · mode</span></div>
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
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn primary" disabled={!origin || !dest} onClick={() => setTick(t => t + 1)} style={{ flex: 1 }}>{routeState === 'loading' ? 'Routing…' : 'Find safe route'}</button>
                <button className="btn ghost" disabled={!origin} onClick={share}>{copied ? 'Copied' : 'Share'}</button>
              </div>
            </div>
          </div>

          <div className="panel brackets">
            <div className="panel-hd"><h3>Safe route</h3>{routes && <span className="sub">{routes.reachable ? 'passable under current conditions' : 'no passable route'}</span>}</div>
            <div className="panel-bd">
              {!dest && <div style={{ fontSize: 12.5, color: 'var(--text-lo)' }}>Set a destination to get a route that avoids flooded roads.</div>}
              {dest && routeState === 'loading' && !routes && <div style={{ fontSize: 12.5, color: 'var(--text-lo)' }}>Computing…</div>}
              {routeErr && <div style={{ fontSize: 12, color: '#FCA5A5', marginBottom: 8 }}>{routeErr}</div>}
              {routes && routes.reachable === false && routes.snapped && (
                <div style={{ padding: '8px 10px', background: 'rgba(239,68,68,0.12)', border: '1px solid #EF444455', borderRadius: 8, marginBottom: 10, fontSize: 12 }}>
                  <b style={{ color: '#FCA5A5' }}>No safe way through right now.</b>
                  {(routes.blocking_segments || []).length > 0 && <div style={{ color: 'var(--text-mid)', marginTop: 4 }}>Blocked by: {routes.blocking_segments.slice(0, 5).map(s => `${s.name || s.highway} (${s.max_depth_m} m)`).join(', ')}</div>}
                </div>
              )}
              {safe && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, padding: '10px 12px', background: 'rgba(10,18,28,0.5)', border: '1px solid #22D3EE44', borderLeft: '3px solid #22D3EE', borderRadius: 8, fontSize: 12 }}>
                    <span><span className="k">DISTANCE</span><br /><span className="mono" style={{ fontSize: 15, fontWeight: 700 }}>{fmtKm(safe.length_m)}</span></span>
                    <span><span className="k">ETA</span><br /><span className="mono" style={{ fontSize: 15, fontWeight: 700 }}>{safe.eta_min} min</span></span>
                    <span><span className="k">WORST ROAD</span><br /><span className="mono" style={{ color: ROUTE_STATUS_COLOR[safe.worst_status], fontWeight: 700 }}>{ROUTE_STATUS_LABEL[safe.worst_status]}</span></span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-hi)' }}>
                    {routes.closed_avoided.length > 0
                      ? <span>Avoids {routes.closed_avoided.length} flooded segment{routes.closed_avoided.length === 1 ? '' : 's'}{normal ? ` (+${fmtKm(Math.max(0, safe.length_m - normal.length_m))} vs the usual way)` : ''}: <span style={{ color: 'var(--text-mid)' }}>{routes.closed_avoided.slice(0, 3).map(s => `${s.name || 'unnamed road'} ${s.max_depth_m} m`).join(', ')}</span></span>
                      : (normal && normal.closed_segments ? `The usual way has ${normal.closed_segments} closed segment${normal.closed_segments === 1 ? '' : 's'}` : 'Same as the usual way — nothing flooded on it right now.')}
                  </div>
                  {safe.worst_status === 'caution' && <div style={{ fontSize: 11.5, color: '#F59E0B' }}>Some stretches have 15 to 30 cm of standing water. Drive slowly, keep to the crown of the road.</div>}
                </div>
              )}
            </div>
          </div>

          <div className="panel brackets">
            <div className="panel-hd"><h3>Roads to avoid now</h3><span className="sub">{most.length} named roads</span></div>
            <div className="panel-bd" style={{ maxHeight: 240, overflowY: 'auto' }}>
              {roadsState === 'loading' && !roads && <div style={{ fontSize: 12.5, color: 'var(--text-lo)' }}>Scoring the road network…</div>}
              {roads && most.length === 0 && <div style={{ fontSize: 12.5, color: 'var(--text-lo)' }}>{raining ? 'No road is affected at the current rainfall.' : 'Dry conditions — every mapped road is open.'}</div>}
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
            Rain from Open-Meteo (observed past 6 h + forecast next 6 h, refreshed every 10 min); statuses from the DEM ponding model unless a community report within 25 m overrides them.
            {model && model.macro_f1 != null ? ` Road risk surrogate: macro F1 ${model.macro_f1} on held-out site ${model.held_out_site}.` : ''}
            {' '}What-if scenarios live in the Flood Simulator.
          </div>
        </div>
      </div>
      <style>{`@media (max-width: 900px) { .routes-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}

window.RoutesScreen = RoutesScreen;
