# ERA5 reanalysis vs TNDMA gauges, per district

Computed 2026-10-09 over 2021-01-01 to 2023-12-26. Station: district mean of the active Revenue-department TNDMA gauges, unreported days counted as dry (OpenCity, public domain). Reanalysis: Open-Meteo archive at the district centroid. This is the label every RIIS weather model learns, so its bias is the models' bias.

| District | Days | Gauges/day | Station mm/yr | ERA5 mm/yr | Ratio | r daily | p99 ratio | Heavy-day POD | Heavy-day FAR |
|---|---|---|---|---|---|---|---|---|---|
| Chennai | 1081 | 11.0 | 1876 | 1616 | 0.861 | 0.512 | 0.623 | 0.188 | 0.5 |
| Kanchipuram | 1080 | 5.4 | 1590 | 1415 | 0.89 | 0.456 | 0.572 | 0.182 | 0.333 |
| Madurai | 1086 | 22.0 | 977 | 1444 | 1.478 | 0.352 | 0.9 | None | 1.0 |
| Coimbatore | 1089 | 22.2 | 1426 | 1394 | 0.978 | 0.344 | 1.193 | None | 1.0 |
| Cuddalore | 1089 | 24.9 | 1599 | 1507 | 0.942 | 0.357 | 0.733 | 0.125 | 0.75 |
| Thanjavur | 1089 | 21.0 | 1318 | 1422 | 1.078 | 0.361 | 0.729 | 0.0 | 1.0 |
| Nilgiris (Ooty) | 1089 | 28.9 | 1859 | 2059 | 1.108 | 0.382 | 0.852 | 0.0 | 1.0 |

Median ratio 0.978, median p99 ratio 0.733, median heavy-day POD 0.125. ratio < 1 means the reanalysis under-reports rain; a p99 ratio well under 1 means it flattens the heavy days the impact engine cares about most.

POD = share of observed heavy days (>= 64.5 mm) that the reanalysis also shows as heavy; FAR = share of reanalysis heavy days with no gauge support. The JSON at app/data/station_bias.json carries monthly bias and quantile tables and is served with every impact response for the district.
