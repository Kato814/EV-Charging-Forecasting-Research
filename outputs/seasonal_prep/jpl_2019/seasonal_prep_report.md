# JPL seasonal preparation report

Status: CONDITIONAL_PASS
Months: 2019-02, 2019-08, 2019-11

## Acquisition

| Month | Official | Probe requests | Local | UTC | Left | Right | Carry | Carry complete | Valid chunks | Expected chunks | Matched | Missing | Orphan |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 1288 | 1 | 1288 | 1288 | 6 | 6 | 1 | 1 | 28 | 28 | 1289 | 0 | 0 |
| 2019-08 | 1509 | 1 | 1509 | 1511 | 2 | 0 | 0 | 0 | 31 | 31 | 1509 | 0 | 0 |
| 2019-11 | 1353 | 1 | 1353 | 1355 | 2 | 0 | 1 | 1 | 30 | 30 | 1354 | 0 | 0 |

## Cleaning

| Month | Attempted | Cleaned | Skipped | Current invalid rate | Pilot invalid rate | Current raw | Current usable | Current retained | Current retained rate | Pilot raw | Pilot usable | Pilot retained | Pilot retained rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 1289 | 1287 | 2 | 0.0015515903801396431 | 0.0015515903801396431 | 8622405 | 8581940 | 8581940 | 0.9953069938143708 | 8627675 | 8587196 | 8587196 | 0.9953082377349634 |
| 2019-08 | 1509 | 1509 | 0 | 0.0 | 0.0 | 9796237 | 9749362 | 9749362 | 0.9952149993921136 | 9795474 | 9748682 | 9748682 | 0.9952230999745393 |
| 2019-11 | 1354 | 1348 | 6 | 0.004431314623338257 | 0.004431314623338257 | 8172792 | 8132700 | 8128880 | 0.9946270503397125 | 8178756 | 8138853 | 8135035 | 0.9946543215129539 |

### Trajectory quarantine

| Month | Trajectory quarantine | Full-session quarantine | Current raw coverage | Current analysis coverage | Pilot raw coverage | Pilot analysis coverage | Quarantine in denominator | Raw retained | Sort repair | Timestamp shift s | Interpolation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 0 | 0 | 1287 | 1287 | 1287 | 1287 | true | true | false | 0 | false |
| 2019-08 | 0 | 0 | 1509 | 1509 | 1509 | 1509 | true | true | false | 0 | false |
| 2019-11 | 1 | 0 | 1348 | 1347 | 1348 | 1347 | true | true | false | 0 | false |

| Month | Current duplicate extras | Pilot duplicate extras | Current conflicts | Pilot conflicts | Boundary points | Boundary sessions | Boundary integral share | Current boundary +/-60 | Pilot boundary +/-60 | Current mode s | Pilot mode s | Current hold s | Pilot hold s | User-input truncation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 2 | 25 | 24 | 1 | 493 | 292 | 3.544160246045563e-05 | 3.0535288075837265e-05 | 0.003284316683863742 | 4 | 4 | 12 | 12 | true |
| 2019-08 | 21 | 94 | 79 | 0 | 5944 | 386 | 0.0013016831551920073 | 0.0011226339162866742 | 0.0031061760633986765 | 4 | 4 | 12 | 12 | true |
| 2019-11 | 59 | 262 | 189 | 3 | 4681 | 313 | 0.001390497003309783 | 0.001226366157962035 | 0.0030691622589650875 | 4 | 4 | 12 | 12 | true |

## Power semantics

| Month | Status | E208 authorized | Pinned commit | Pinned formula | Mapping rate | Minimum kWh | Minimum coverage | Eligible | Retained | Retained rate | Voltage Q1 | Voltage median | Voltage Q3 | Voltage IQR | MdAPE | P90 APE | Aggregate relative error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | KW_RECONSTRUCTION_CANDIDATE | false | 14e723b11339e56ca3afd2bf4969f9e4bc8c2623 | E_208_kWh=208*ampere_hours/1000 | 1.0 | 0.5 | 0.9 | 1287 | 1208 | 0.9386169386169386 | 202.96523304643932 | 204.60849148138112 | 206.3852258980197 | 3.419992851580389 | 0.01783290960658708 | 0.03452497537642209 | 0.012671694114568548 |
| 2019-08 | KW_RECONSTRUCTION_CANDIDATE | false | 14e723b11339e56ca3afd2bf4969f9e4bc8c2623 | E_208_kWh=208*ampere_hours/1000 | 1.0 | 0.5 | 0.9 | 1509 | 1418 | 0.9396951623591783 | 202.20479756878726 | 204.0083715267089 | 206.35871350182026 | 4.153915933033005 | 0.021752629612152248 | 0.04051788089281101 | 0.016798426177806733 |
| 2019-11 | CURRENT_PROXY_ONLY | false | 14e723b11339e56ca3afd2bf4969f9e4bc8c2623 | E_208_kWh=208*ampere_hours/1000 | 1.0 | 0.5 | 0.9 | 1348 | 1075 | 0.7974777448071216 | 203.49776290829868 | 205.53753252176148 | 208.37696938810404 | 4.879206479805362 | 0.01724061534934028 | 0.037698012433495826 | 0.00892301009195581 |

## 15-minute

| Month | Bins | Valid 80 | Valid 90 | Valid 95 | Valid 80 rate | Valid 90 rate | Valid 95 rate | Missing 80 rate | Missing 90 rate | Missing 95 rate | Longest missing | Peak current | Max ramp | DST extra bins | Integral status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 2688 | 2646 | 2640 | 2638 | 0.984375 | 0.9821428571428571 | 0.9813988095238095 | 0.015625 | 0.017857142857142905 | 0.018601190476190466 | 17 | 765.5 | 328.314 | 0 | PASS |
| 2019-08 | 2976 | 2960 | 2954 | 2943 | 0.9946236559139785 | 0.9926075268817204 | 0.9889112903225806 | 0.005376344086021501 | 0.007392473118279619 | 0.011088709677419373 | 9 | 755.8 | 253.44233333 | 0 | PASS |
| 2019-11 | 2884 | 2775 | 2769 | 2762 | 0.9622052704576977 | 0.960124826629681 | 0.9576976421636616 | 0.03779472954230234 | 0.039875173370318984 | 0.0423023578363384 | 25 | 754.9 | 183.18933333 | 4 | PASS |

| Month | Weekday bins | Weekday valid | Weekday mean | Weekday median | Weekend bins | Weekend valid | Weekend mean | Weekend median |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 1920 | 1895 | 189.52683571 | 44.89988889 | 768 | 745 | 7.51604444 | 0.0 |
| 2019-08 | 2112 | 2094 | 195.05122424 | 93.88922222 | 864 | 860 | 5.21839922 | 0.0 |
| 2019-11 | 2016 | 1919 | 182.94437658 | 60.01811111 | 868 | 850 | 18.13469595 | 0.0 |

## M1-M3

| Month | Scheduled | Formal | Labels 15 | Labels 240 | M1 | M2 | M3 | M1 width | M2 width | M3 width | M1 encoded | M2 encoded | M3 encoded | Leakage violations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 2577 | 2439 | 2529 | 2529 | 2439 | 2439 | 2439 | 96 | 6 | 11 | 195 | 204 | 391 | 0 |
| 2019-08 | 2865 | 2784 | 2843 | 2843 | 2784 | 2784 | 2784 | 96 | 6 | 11 | 195 | 204 | 391 | 0 |
| 2019-11 | 2773 | 2524 | 2658 | 2658 | 2524 | 2524 | 2524 | 96 | 6 | 11 | 195 | 204 | 391 | 0 |

| Month | M1 history missing | M2 current missing | M2 pilot sum missing | M2 pilot mean missing | M3 current missing | M3 recent mean missing | M3 recent peak missing | M3 pilot missing | M3 departure missing | M3 energy missing | Feature whitelist |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2019-02 | 0.01686142 | 0.01066011 | 0.01066011 | 0.01066011 | 0.0022648 | 0.0001192 | 0.0001192 | 0.0022648 | 0.03951486 | 0.03951486 | PASS |
| 2019-08 | 0.00723255 | 0.00933908 | 0.00933908 | 0.00933908 | 0.00269376 | 0.00015393 | 0.00015393 | 0.00261679 | 0.02506478 | 0.02506478 | PASS |
| 2019-11 | 0.03420497 | 0.00475436 | 0.00396197 | 0.00396197 | 0.00898286 | 0.00024185 | 0.00024185 | 0.00487148 | 0.02788143 | 0.02788143 | PASS |

## Security

Aggregate-only evidence: YES
Raw inventories unchanged: YES
Network access: NO
Training executed: NO
M4 generated: NO
Config SHA256: 541268b66d3eaad031fb7551fd0e10409dba7c35fb539856ce1936b85160c8e9
Code commit: 7b5b6e60177c328666896e3f26fe9e037d34e8b7
2019-02 metadata source SHA256: bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
2019-02 metadata record SHA256: 62f8d00dead0b0f6ebc8f22083904076b42a82a7ae420d17f258bcdd982a9a66
2019-02 official reference SHA256: 2a6916f4d7c5272f3ec178bdfb2ab69d90e6117cafd77bf9375ef219e1938fef
2019-02 raw SHA256: 70a0a6178d39607045a0e048b119ef391fa7a6be96261020a2896e6a4d8742a0
2019-02 processed SHA256: 996c455e482d1e50e374530f29fb8bacd3a0122840655ea4edd9ab3b5a28ebee
2019-02 snapshot SHA256: 436db41adca64af2b0758916a83480035638d1912e8ce90c8239186988b6711b
2019-08 metadata source SHA256: bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
2019-08 metadata record SHA256: 62f8d00dead0b0f6ebc8f22083904076b42a82a7ae420d17f258bcdd982a9a66
2019-08 official reference SHA256: d277233d62fca3665e263ee68d580b827d169313bbb50a64ea8c3a071aa4916d
2019-08 raw SHA256: 06b16066eeba18ef33ae0eb26a348111b316d213a8f9be88e9c9067059140f10
2019-08 processed SHA256: 8a457ef11680350dd6acacf1473a304b0911b9c8585e478c44d16dba42b71f57
2019-08 snapshot SHA256: 50dd7ce3f6f21fa66bc0b520201f88e6ddf061185f040424a87e8b327770cc11
2019-11 metadata source SHA256: bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a
2019-11 metadata record SHA256: 62f8d00dead0b0f6ebc8f22083904076b42a82a7ae420d17f258bcdd982a9a66
2019-11 official reference SHA256: 692c3e304ceef3f42a786cf44337e4828c32cdc319bda6a816c34e2fbf695314
2019-11 raw SHA256: 77e7b261d488aec79a5d21648fbe1a9825b60cb1df65658de797fc2b404007f3
2019-11 processed SHA256: 287e4cd005f60b417b63a24450f1d20bfac68f42ba62bca416977290f4d15e9e
2019-11 snapshot SHA256: 0fcec7d93da69ddbb9674e432db88c4a82801370577a1e2a5e020b9b5d6d9dda

## Decision

| Month | Preparation status | Power status | Leakage status | User-input truncation ready |
| --- | --- | --- | --- | --- |
| 2019-02 | PASS | KW_RECONSTRUCTION_CANDIDATE | PASS | true |
| 2019-08 | PASS | KW_RECONSTRUCTION_CANDIDATE | PASS | true |
| 2019-11 | PASS_WITH_TRAJECTORY_QUARANTINE | CURRENT_PROXY_ONLY | PASS | true |
