# Test Data in the Student Database (T014.1)

> **Generated:** 2026-10-24 08:08 Central America Standard Time (read-only query of `mentor_pro`)
> **Action taken:** none. Cleanup requires explicit Product Owner approval.

## Summary

| Class | Sessions | Questions | Answers |
|-------|----------|-----------|---------|
| confirmed_test | 103 | 424 | 308 |
| probable_test | 14 | 68 | 68 |
| presumed_student | 2 | 9 | 5 |
| **Total** | 119 | 501 | 381 |

Classification rules are in the docstring of `scripts/dev/test_data_report.py`.

## Ambiguous: Probable Test Sessions (decision needed)

| Session | Created | Subject | Objectives | Difficulty | Status | Bank | Answers | Evidence |
|---------|---------|---------|------------|------------|--------|------|---------|----------|
| `fa72cb389c32` | 2026-10-23 14:42:44 | matematicas | M02, M04, M05 | medium | partial | 0/4 | 4 | 96 s from a confirmed test session; scripted configuration answered ABCD |
| `75b0d0127384` | 2026-10-23 14:55:47 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | scripted configuration answered ABCDA |
| `1741896654a2` | 2026-10-23 20:44:14 | matematicas | M02, M04, M05 | medium | complete | 5/5 | 5 | 7 s from a confirmed test session; scripted configuration answered ABCDA |
| `573772cc0da4` | 2026-10-23 20:45:58 | matematicas | M02, M04, M05 | medium | complete | 5/5 | 5 | 7 s from a confirmed test session; scripted configuration answered ABCDA |
| `594a8062849a` | 2026-10-23 20:48:20 | matematicas | M02, M04, M05 | hard | complete | 0/5 | 5 | scripted configuration answered ABCDA |
| `2ebaa3044aec` | 2026-10-23 20:57:49 | matematicas | M02, M06 | hard | partial | 2/4 | 4 | scripted configuration answered ABCD |
| `25f6b6d58a55` | 2026-10-23 21:04:48 | matematicas | M02, M04, M05 | medium | complete | 5/5 | 5 | scripted configuration answered ABCDA |
| `dd9b7e252b1c` | 2026-10-23 21:04:54 | matematicas | M02, M06 | medium | complete | 2/5 | 5 | scripted configuration answered ABCDA |
| `d9a634a65f63` | 2026-10-23 21:11:15 | matematicas | M02, M04, M05 | hard | complete | 5/5 | 5 | 6 s from a confirmed test session |
| `69ebb2addece` | 2026-10-23 21:12:21 | matematicas | M02, M04, M05 | medium | complete | 5/5 | 5 | 7 s from a confirmed test session; scripted configuration answered ABCDA |
| `aca0d808549b` | 2026-10-23 21:12:28 | matematicas | M02, M04, M05 | hard | complete | 5/5 | 5 | 14 s from a confirmed test session |
| `128cf1b3a344` | 2026-10-23 21:14:00 | matematicas | M02, M04, M05 | medium | complete | 5/5 | 5 | 3 s from a confirmed test session; scripted configuration answered ABCDA |
| `8e57fa5a67df` | 2026-10-23 22:25:59 | matematicas | M02, M04, M05 | medium | complete | 5/5 | 5 | 3 s from a confirmed test session; scripted configuration answered ABCDA |
| `bf01fce70a0c` | 2026-10-23 22:32:46 | matematicas | M02, M04, M05 | medium | complete | 5/5 | 5 | 3 s from a confirmed test session; scripted configuration answered ABCDA |

## Presumed Student Sessions

| Session | Created | Subject | Objectives | Difficulty | Status | Bank | Answers | Evidence |
|---------|---------|---------|------------|------------|--------|------|---------|----------|
| `021d7f83fca0` | 2026-10-23 17:03:13 | ciencias | C06 | mixed | complete | 0/5 | 5 | — |
| `bac7a5b55a5c` | 2026-10-23 22:10:55 | espanol | EL06, EL07, EL08 | medium | partial | 0/4 | 0 | — |

## Confirmed Test Sessions

| Session | Created | Subject | Objectives | Difficulty | Status | Bank | Answers | Evidence |
|---------|---------|---------|------------|------------|--------|------|---------|----------|
| `6e3b83102120` | 2026-10-23 14:38:19 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `7f549cc62e1a` | 2026-10-23 14:38:27 | espanol | EL01, EL02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `4b180ed4fd64` | 2026-10-23 14:38:35 | ciencias | C01, C02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `ce3e7a38d7c5` | 2026-10-23 14:38:43 | estudios_sociales | ES01, ES02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `89cdf62d2f48` | 2026-10-23 14:38:51 | matematicas | M02, M05 | medium | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `6e06f024a43e` | 2026-10-23 14:38:55 | ciencias | C01, C02 | medium | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `de3384c0a5a8` | 2026-10-23 14:39:07 | estudios_sociales | ES01, ES02 | medium | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `9d6360058cbd` | 2026-10-23 14:39:12 | espanol | EL01, EL02 | medium | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `afd8734645e7` | 2026-10-23 14:39:18 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `58904b3d996d` | 2026-10-23 14:40:08 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `98d0352c177b` | 2026-10-23 14:40:16 | espanol | EL01, EL02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `a613e56614f3` | 2026-10-23 14:40:24 | ciencias | C01, C02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `23e921afbec0` | 2026-10-23 14:40:32 | estudios_sociales | ES01, ES02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `8a42943870de` | 2026-10-23 14:40:40 | matematicas | M02, M05 | medium | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `7d51d3045122` | 2026-10-23 14:40:45 | ciencias | C01, C02 | medium | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `9e906b3db6b5` | 2026-10-23 14:40:57 | estudios_sociales | ES01, ES02 | medium | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `0fcfd2feb73f` | 2026-10-23 14:41:02 | espanol | EL01, EL02 | medium | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `796e148c95ad` | 2026-10-23 14:41:08 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `1cbe3cda0cab` | 2026-10-23 19:51:13 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `5ef328bb2aa7` | 2026-10-23 19:51:21 | espanol | EL01, EL02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `a4b93f0d1093` | 2026-10-23 19:51:30 | ciencias | C01, C02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `f50b7e12e6b2` | 2026-10-23 19:51:39 | estudios_sociales | ES01, ES02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `dc0130eeee2f` | 2026-10-23 19:51:48 | matematicas | M02, M05 | medium | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `c21529cfc6e1` | 2026-10-23 19:51:52 | ciencias | C01, C02 | medium | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `0e7e5caec924` | 2026-10-23 19:52:02 | estudios_sociales | ES01, ES02 | medium | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `fb8068dc5fe2` | 2026-10-23 19:52:06 | espanol | EL01, EL02 | medium | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `ca1c4a9c4ca1` | 2026-10-23 19:52:13 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `d7c9dd141b1c` | 2026-10-23 19:52:36 | matematicas | M02, M04 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `a5865e9822f1` | 2026-10-23 19:52:55 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `989d781d44c0` | 2026-10-23 19:53:03 | espanol | EL01, EL02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `130ebac036cf` | 2026-10-23 19:53:13 | ciencias | C01, C02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `f0872010979f` | 2026-10-23 19:53:20 | estudios_sociales | ES01, ES02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `039cb7229f11` | 2026-10-23 19:53:29 | matematicas | M02, M05 | medium | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `92a48589c7be` | 2026-10-23 19:53:33 | ciencias | C01, C02 | medium | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `b65b610ff192` | 2026-10-23 19:53:43 | estudios_sociales | ES01, ES02 | medium | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `3b4ca743b362` | 2026-10-23 19:53:48 | espanol | EL01, EL02 | medium | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `29e84b122392` | 2026-10-23 19:53:54 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `b25ee7ac8999` | 2026-10-23 19:54:41 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `d2ebe9f108bb` | 2026-10-23 19:54:48 | espanol | EL01, EL02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `618f5ee1e9cd` | 2026-10-23 19:54:57 | ciencias | C01, C02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `a6a17a066f4f` | 2026-10-23 19:55:05 | estudios_sociales | ES01, ES02 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `fe436e0cbd8e` | 2026-10-23 19:55:13 | matematicas | M02, M05 | medium | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `314f3f7d1c03` | 2026-10-23 19:55:18 | ciencias | C01, C02 | medium | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `f04e2d8cd325` | 2026-10-23 19:55:30 | estudios_sociales | ES01, ES02 | medium | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `96adfaf585b1` | 2026-10-23 19:55:35 | espanol | EL01, EL02 | medium | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `c096f195abba` | 2026-10-23 19:55:42 | matematicas | M02, M04, M05 | medium | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `321e5813abef` | 2026-10-23 20:43:06 | matematicas | M02, M04, M05 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `34c3baf53f54` | 2026-10-23 20:43:14 | espanol | EL01, EL02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `5c6647d1faeb` | 2026-10-23 20:43:25 | ciencias | C01, C02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `779e5ad79858` | 2026-10-23 20:43:34 | estudios_sociales | ES01, ES02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `ba73bd7813fb` | 2026-10-23 20:43:43 | matematicas | M02, M05 | hard | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `5a40be2e4042` | 2026-10-23 20:43:49 | ciencias | C01, C02 | hard | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `f12705b8fe18` | 2026-10-23 20:44:01 | estudios_sociales | ES01, ES02 | hard | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `1e32b622a79f` | 2026-10-23 20:44:07 | espanol | EL01, EL02 | hard | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `8f1ab1f1b8b6` | 2026-10-23 20:44:21 | matematicas | M02, M04, M05 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `bd9a1bcfc457` | 2026-10-23 20:44:50 | matematicas | M02, M04, M05 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `a83e05eb501f` | 2026-10-23 20:44:59 | espanol | EL01, EL02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `89d7dd9af2a2` | 2026-10-23 20:45:09 | ciencias | C01, C02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `a53b861216dd` | 2026-10-23 20:45:19 | estudios_sociales | ES01, ES02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `e4477c96fb85` | 2026-10-23 20:45:28 | matematicas | M02, M05 | hard | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `114afad31983` | 2026-10-23 20:45:33 | ciencias | C01, C02 | hard | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `4d2c0cd314af` | 2026-10-23 20:45:45 | estudios_sociales | ES01, ES02 | hard | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `78a8566e8cd2` | 2026-10-23 20:45:51 | espanol | EL01, EL02 | hard | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `3358cfc37574` | 2026-10-23 20:46:05 | matematicas | M02, M04, M05 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `490386df4969` | 2026-10-23 21:11:21 | espanol | EL01, EL02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `100c6a5904b6` | 2026-10-23 21:11:31 | ciencias | C01, C02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `d10545e3329c` | 2026-10-23 21:11:41 | estudios_sociales | ES01, ES02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `70ca8235b8f2` | 2026-10-23 21:11:51 | matematicas | M02, M05 | hard | complete | 4/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `8d9488142ebb` | 2026-10-23 21:11:56 | ciencias | C01, C02 | hard | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `c97ca499eadb` | 2026-10-23 21:12:08 | estudios_sociales | ES01, ES02 | hard | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `13c9380839b5` | 2026-10-23 21:12:14 | espanol | EL01, EL02 | hard | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `60378d03f35f` | 2026-10-23 21:13:04 | matematicas | M10, M11, M12 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `062593fd4582` | 2026-10-23 21:13:12 | espanol | EL01, EL02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `6b0dd819d4c7` | 2026-10-23 21:13:21 | ciencias | C01, C02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `3b7b5f17bd17` | 2026-10-23 21:13:31 | estudios_sociales | ES01, ES02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `e47a3b0d4dbb` | 2026-10-23 21:13:38 | matematicas | M10, M12 | hard | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `41b933e03bbd` | 2026-10-23 21:13:42 | ciencias | C01, C02 | hard | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `655034d326be` | 2026-10-23 21:13:51 | estudios_sociales | ES01, ES02 | hard | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `baee3ed9fb46` | 2026-10-23 21:13:55 | espanol | EL01, EL02 | hard | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `0146de8246f2` | 2026-10-23 21:14:04 | matematicas | M10, M11, M12 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `7b6b6971924e` | 2026-10-23 22:25:11 | matematicas | M10, M11, M12 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `ce0ca5336f2f` | 2026-10-23 22:25:17 | espanol | EL01, EL02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `a5cee8e3fc7d` | 2026-10-23 22:25:23 | ciencias | C01, C02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `fe2a91a2aad3` | 2026-10-23 22:25:29 | estudios_sociales | ES01, ES02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `42ca8d737c94` | 2026-10-23 22:25:35 | matematicas | M10, M12 | hard | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `6c5d81ae1b19` | 2026-10-23 22:25:40 | ciencias | C01, C02 | hard | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `1380fa29113f` | 2026-10-23 22:25:49 | estudios_sociales | ES01, ES02 | hard | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `49257d921911` | 2026-10-23 22:25:53 | espanol | EL01, EL02 | hard | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `7846954a731d` | 2026-10-23 22:26:02 | matematicas | M10, M11, M12 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `4e94a1d35ff8` | 2026-10-23 22:31:59 | matematicas | M10, M11, M12 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `870eccf0f86c` | 2026-10-23 22:32:05 | espanol | EL01, EL02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `a9de2dde5baa` | 2026-10-23 22:32:11 | ciencias | C01, C02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `d6641d630d81` | 2026-10-23 22:32:17 | estudios_sociales | ES01, ES02 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `9a94a75783fc` | 2026-10-23 22:32:23 | matematicas | M10, M12 | hard | complete | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `089a858f727d` | 2026-10-23 22:32:28 | ciencias | C01, C02 | hard | complete | 0/5 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `c2ede106c8f8` | 2026-10-23 22:32:36 | estudios_sociales | ES01, ES02 | hard | failed | 0/0 | 0 | practice_set_id set-mock-… |
| `3c443f867344` | 2026-10-23 22:32:41 | espanol | EL01, EL02 | hard | partial | 0/2 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `d9a527ef387c` | 2026-10-23 22:32:49 | matematicas | M10, M11 | hard | complete, cancelled | 0/5 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `f17368f87215` | 2026-10-23 22:32:55 | matematicas | M10, M12 | hard | complete, cancelled | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `4651df332628` | 2026-10-23 22:33:00 | matematicas | M11, M12 | hard | partial, cancelled | 0/2 | 1 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `0c220b74fce8` | 2026-10-23 22:33:05 | matematicas | M10, M11, M12 | hard | complete | 0/5 | 5 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `b1ee6e6d3667` | 2026-10-23 22:33:11 | matematicas | M10, M11 | hard | complete, cancelled | 0/5 | 2 | practice_set_id set-mock-…; mock or e2e item identifiers |
| `6c523f88a7da` | 2026-10-23 22:33:17 | matematicas | M10, M12 | hard | complete, cancelled | 0/5 | 0 | practice_set_id set-mock-…; mock or e2e item identifiers |
