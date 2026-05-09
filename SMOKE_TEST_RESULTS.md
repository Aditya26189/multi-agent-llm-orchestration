# Smoke Test Results

**Date:** 2026-05-09
**Commit:** d228dbf

## Static Checks
| Check | Result |
|-------|--------|
| No OpenAI references | ✅ PASS |
| No hardcoded credentials | ✅ PASS |
| No placeholder GitHub URL | ✅ PASS |
| Correct vector dimension (768) | ✅ PASS |
| .env not committed | ✅ PASS |
| Correct pgvector image | ✅ PASS |
| No fake percentage numbers | ✅ PASS |
| asyncio.Lock in budget manager | ✅ PASS |
| Dict format in all HTTPExceptions | ✅ PASS |
| Seeder in docker-compose | ✅ PASS |
| docs/tools.md exists (>80 lines) | ✅ PASS |
| All 3 new doc sections in evaluation.md | ✅ PASS |
| Dynamic routing section in README | ✅ PASS |

## Functional Tests
| Test | Result | Notes |
|------|--------|-------|
| docker compose up --build --wait | ✅ PASS | All 5 services healthy |
| Seeder init container | ✅ PASS | 30 documents seeded |
| make test | ✅ PASS | 64/64 tests passing |
| make eval | ✅ PASS | 15/15 test cases scored |
| DB justification strings | ✅ PASS | Non-null JSONB per dimension |
| SSE stream (AGENT_START/TOKEN/done) | ✅ PASS | Tokens streamed live |
| Injection rejection (400) | ✅ PASS | INJECTION_DETECTED returned |
| Trace endpoint | ✅ PASS | 42 events returned |
| Eval/latest endpoint | ✅ PASS | total_score=0.885 |
| Logquery UI (:8001) | ✅ PASS | UI renders |
| Error format (JOB_NOT_FOUND) | ✅ PASS | error_code field present |

## Git History
| Check | Result |
|-------|--------|
| Total commits | 32 commits |
| Conventional commit format | ✅ PASS |
| No mega-commits | ✅ PASS |

**Overall: READY FOR SUBMISSION**
