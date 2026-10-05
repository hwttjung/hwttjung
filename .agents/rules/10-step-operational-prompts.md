---
trigger: always_on
---

# 10-Step Operational Prompts (STEP 0 ~ STEP 9)

실제 개발 세션(Agent Chat)에서 각 단계별로 에이전트에게 순차 투입하는 표준 엔지니어링 프롬프트 세트입니다.

## STEP 0 — Repository Reconnaissance
[Task: Repository Reconnaissance]
Do NOT modify or create any code or files yet.
Before implementing the current task ({Insert Task Summary}), conduct a thorough investigation of the existing codebase.
You must inspect and verify the following:
1. Project directory structure (`src/`, `models/`, `collectors/`, `tests/`, etc.)
2. Existing files, classes, or functions related to this functionality
3. Relevant Pydantic models and data schemas
4. Existing test suites and fixture structures (`tests/fixtures/`)
5. Project dependencies (`pyproject.toml`, `requirements.txt`, etc.)
6. Configuration files (`.env`, `config.py`, etc.)
7. Existing call sites and duplicate implementation risks
8. Potential blast radius and breaking change risks

Output your investigation strictly using the following headers:
- Existing Components:
- Related Files:
- Existing Interfaces:
- Existing Tests:
- Dependencies:
- Potential Conflicts:
- Expected Change Scope:

Output only the reconnaissance report. Do NOT start implementation.

## STEP 1 — Task Contract
[Task: Task Contract]
Based on the STEP 0 reconnaissance report, transform the requirements of this task into an unambiguous implementation contract.
Explicitly define the following:
1. Input: Input data types and acceptance constraints
2. Output: Return types and data structures
3. Public Interface: Complete class and method signatures
4. Data Model: Pydantic schemas (Strict type boundary, NO `Any`)
5. Invariants:
   - e.g., Title must be unescaped plain text with HTML entities and CDATA stripped
   - e.g., `published_at` must be a timezone-aware UTC datetime
   - e.g., Duplicate items with identical link/guid within a single feed must be deduplicated in-memory
6. Error Conditions: Complete list of potential failure scenarios
7. Side Effects: State changes or external side effects
8. External Dependencies: Libraries to be used (note if any new ones are requested)
9. Non-Goals: Explicitly list what this task will NOT do

Do not assume requirements. If there are conflicts with existing code, report them immediately before implementing.

## STEP 2 — Scope Lock
[Task: Scope Lock]
Lock the exact set of files allowed to be modified for this task.
Declare the scope using the following format, including a one-line justification for each file:

Allowed Files:
- {file_path}: {One-line reason for modification}

Potentially Required Files:
- {file_path}: {Condition under which modification is necessary}

Forbidden Areas:
- Database schemas/migrations, API controllers, auth, deployment configurations, and all other unrelated layers.

Rule: If you discover during implementation that a file not listed above must be modified, you MUST stop work immediately, explain the reason, and request user approval.

## STEP 3 — Acceptance Criteria
[Task: Acceptance Criteria]
Define clear specifications for normal and failure behaviors before designing tests or code.
Specify the following:
1. Normal inputs and expected outputs
2. Input validation rules
3. Domain invariants (text sanitization, UTC normalization, in-memory deduplication)
4. Exception conditions and handling strategies:
   - HTTP 4xx, invalid URLs -> Fail fast immediately
   - Unrecoverable XML parsing errors -> Raise `FeedParseError` (Never return empty lists `[]`)
   - Items missing required fields -> Drop/skip individual malformed item, retain valid items
   - Unexpected exceptions -> Re-raise to higher layer with error logs
5. Retry & Timeout Policies:
   - Timeout / ConnectionError / 5xx: Maximum 3 retries with Exponential Backoff
   - HTTP 429: Delayed retry based on the `Retry-After` header
6. Side-effect policies

Define actual system behavior requirements, not artificial shortcuts designed merely to pass tests.

## STEP 4 — Test Design
[Task: Test Design]
Do NOT write the business implementation code yet.
Write isolated `pytest` test suites based strictly on the approved Acceptance Criteria.
Requirements:
1. Hermetic Testing:
   - Never write unit tests that rely on external internet connectivity.
   - Fully isolate all external network requests using mocks/stubs (`respx`, `responses`, etc.).
2. Test Fixtures (`tests/fixtures/`):
   - Provide concrete XML fixture files (`valid_rss.xml`, `cdata_and_entities.xml`, `missing_fields.xml`, `atom_feed.xml`, etc.).
3. Test Scope:
   - Normal inputs, boundary values, and malformed inputs
   - External network failures, timeouts, retries, and validation errors
   - HTML entity decoding, CDATA extraction, and UTC datetime conversion
   - Single item failure handling (verifying that one malformed item does not crash the entire feed)
   - Verifying that severe parse failures raise `FeedParseError` instead of returning `[]`
   - Regression prevention tests for existing behavior
4. Existing Test Safety:
   - Do NOT delete or weaken any existing tests.

Output only interface stubs (`pass` or `raise NotImplementedError`), fixture files, and complete test suites.

## STEP 5 — Implementation
[Task: Implementation]
Implement the business logic to fully satisfy the Task Contract and Acceptance Criteria.
Strict Constraints:
1. Do NOT modify any file outside the Scope Lock.
2. Do NOT alter existing features or public signatures without approval.
3. Do NOT add new dependencies without explicit permission.
4. `Any` is strictly banned. Validate external inputs at the boundary using Pydantic models.
5. Handle exceptions by specific types. Never swallow errors with `except Exception:`.
6. Apply explicit timeouts (Connect: 5.0s, Read: 10.0s) to all network calls.
7. Apply Exponential Backoff retries (Max 3) only to defined transient errors.
8. Never weaken or alter test assertions to force tests to pass.

Output the complete source code for each modified file with its exact file path.

## STEP 6 — Automated Verification
[Task: Automated Verification]
Do NOT rely on visual self-inspection. Execute the actual verification toolchain in the terminal environment.
Commands to run:
1. `pytest`
2. `pytest --cov` (Verify test coverage)
3. `ruff check .`
4. `mypy .`
5. Any additional project verification scripts

If any verification fails:
1. Analyze the root cause
2. Apply minimal fixes strictly within the Scope Lock
3. Re-run the verification commands until all pass
⚠️ Never bypass errors by deleting tests or lowering assertion standards.

Report the final results using this format:
- Test Result:
- Type Check Result:
- Lint Result:
- Remaining Warnings:
- Known Limitations:

## STEP 7 — Regression / Diff Review
[Task: Regression and Diff Review]
Review the actual Git working tree changes before finalizing the task.
Inspect the following terminal outputs:
1. `git status`
2. `git diff --stat`
3. `git diff`

Checklist:
- Were any files outside the Scope Lock modified? (If yes, do NOT finalize; report the cause immediately)
- Are there any leftover temporary files, debugging code, or stray print statements?
- Were any public APIs or existing test files modified or weakened?
- Were any unnecessary dependencies added?
- Is there any risk of regression in existing functionality?

⚠️ Never approve changes solely because tests passed. Provide a summary of your review findings.

## STEP 8 — Finalization
[Task: Finalization]
Evaluate the task against the Definition of Done (DoD).
- [ ] Requirements fully implemented
- [ ] Acceptance Criteria fully satisfied
- [ ] Unit tests passing 100%
- [ ] Existing regression test suite passing
- [ ] `mypy` type check passing
- [ ] `ruff` linter passing
- [ ] Scope Lock strictly observed
- [ ] No unapproved dependencies added
- [ ] Git diff reviewed and confirmed clean
- [ ] Exception handling and Silent Failure checks verified
- [ ] Known limitations documented

If even a single item remains incomplete, do NOT mark the task as complete.

Output the final report using this format:
Status:
Changed Files:
Tests:
Validation:
Dependencies:
Known Limitations:
Remaining Risks:

## STEP 9 — Context Handoff
[Task: Context Handoff]
Summarize the key contracts and architectural decisions so the next agent session can resume work without guessing design intentions.
Provide the following:
1. Public Interface: Classes, methods, and signatures
2. Data Contract: Core Pydantic models
3. Invariants: Enforced domain rules
4. Error Contract: Defined custom exceptions
5. Retry / Timeout Policy: Applied retry limits, targets, and timeouts
6. Dependencies: External packages used
7. Tests: Added fixtures and test coverage summary
8. Design Decisions (Explain the 'Why'):
   - Why are malformed items dropped rather than aborting the feed?
   - Why are HTTP 404 errors not retried?
   - Why must `published_at` be forced to a timezone-aware UTC datetime?
9. Known Limitations: Current architectural constraints
10. Changed Files: Complete list of modified files
11. Next Task: Exact next step for the subsequent session

Omit verbose source code and internal implementation details. Provide a concise, executive technical handoff.
