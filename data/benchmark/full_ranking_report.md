# Full submission ranking (local mirror)

- Generated: 2026-08-19T23:57:44Z
- Mirror: `data/benchmark/mirror`
- Packages: 924
- GeoJSON land_use populated: 924
- metrics.json land_use populated: 27

## Top 30 by geometry_score (real GeoJSON counts)

| rank | login | slug | score | LU | B | R | fig_kb | pass |
|------|-------|------|-------|----|----|-----|--------|------|
| 1 | bit40303-ops | jingzhang-co-intelligence-loop | 6040.03 | 5 | 4530 | 2494 | 980.3 | True |
| 2 | chenxuan999 | centennial-jingzhang-ai-belt | 4758.12 | 1126 | 898 | 594 | 351.2 | True |
| 3 | UncleJ-h | urbanos-studio | 4242.0 | 386 | 1678 | 2112 | 2279.8 | True |
| 4 | Nizai199 | centennial-belt-proposal | 3323.57 | 893 | 311 | 5 | 1810.7 | True |
| 5 | gymaira1990-jpg | jingzhang-memory-corridor | 2596.07 | 9 | 1615 | 1382 | 1130.7 | True |
| 6 | RanchoGoose | capillary-jingzhang | 2127.5 | 504 | 217 | 97 | 2931.4 | True |
| 7 | Jannhsu | ren-belt-jingzhang-ai-innovation-corridor | 2052.0 | 120 | 1332 | 20 | 3226.0 | True |
| 8 | kuankqaq | zhilian-jingzhang | 2036.09 | 469 | 396 | 14 | 760.9 | True |
| 9 | ivydiana | jingzhang-ai-civic-weave | 1964.8 | 6 | 1674 | 91 | 773.0 | True |
| 10 | mininggoat1 | jingzhang-renzi-spine | 1817.0 | 68 | 1256 | 14 | 4169.8 | True |
| 11 | savon66 | jingzhang-ai-innovation-belt | 1619.46 | 249 | 192 | 811 | 1249.6 | True |
| 12 | JacksonFinn1020 | switchback-ai-line | 1556.0 | 218 | 533 | 38 | 2089.7 | True |
| 13 | JIQINGFENG0818 | jingzhang-gauge | 1526.0 | 167 | 552 | 246 | 2051.4 | True |
| 14 | jinghy06 | jingzhang-ai-belt-concept | 1484.17 | 367 | 91 | 15 | 1346.7 | True |
| 15 | dawnc | centennial-jingzhang-self-reliance-belt | 1471.68 | 348 | 127 | 9 | 1461.8 | True |
| 16 | linzhuo606 | the-ai-line | 1435.5 | 168 | 573 | 17 | 2425.8 | True |
| 17 | xchaor | kongtian-jingzhang-ai-belt | 1396.8 | 164 | 627 | 24 | 1158.0 | True |
| 18 | xiaopi668 | jingzhang-ai-belt | 1370.33 | 108 | 798 | 11 | 928.3 | True |
| 19 | MisakaMikoto114514hhh | jingzhang-open-gauge | 1335.61 | 101 | 824 | 12 | 526.1 | True |
| 20 | xhily | jingzhang-ai-innovation-corridor | 1326.12 | 337 | 123 | 5 | 396.2 | True |
| 21 | xhily | jingzhang-intelligent-artery | 1322.14 | 341 | 117 | 4 | 301.4 | True |
| 22 | Anshengdesign | jingzhang-living-line | 1321.24 | 98 | 782 | 41 | 747.4 | True |
| 23 | MartinForReal | adaptive-flow-network | 1312.19 | 257 | 113 | 366 | 951.9 | True |
| 24 | wuxiangru915 | trailblazers-belt | 1286.94 | 49 | 876 | 8 | 1099.4 | True |
| 25 | inming | jingzhang-mainline | 1216.85 | 193 | 375 | 30 | 978.5 | True |
| 26 | dengyupeng999-create | dyp15-exploration | 1215.35 | 1 | 0 | 1975 | 748.5 | True |
| 27 | cssMV | spike-belt | 1213.33 | 187 | 320 | 19 | 1728.3 | True |
| 28 | lpzhawei | centennial-jingzhang-ai-corridor | 1211.08 | 258 | 164 | 37 | 1045.8 | True |
| 29 | FUSU123fusu | century-rail-ai-origin | 1150.42 | 29 | 790 | 13 | 1169.2 | True |
| 30 | xr843 | jingzhang-two-way-line | 1142.79 | 189 | 244 | 15 | 1742.9 | True |

## Methodology

geometry_score = pass*100 + ready*50 + land_use_geo*3 + buildings_geo + roads_geo*0.5 + min(figure_kb/10, 200). Feature counts from local GeoJSON, not metrics.json.
