# Agent Harness Architecture & Hexagonal Refactor Implementation Plan

This plan introduces a domain-driven, hexagonal Agent Harness into LYOKO to replace procedural tool loops, adding automatic skill/runbook matching, smart head-and-tail output truncation with file scratchpad offloading, and structured execution.

## Proposed Changes

### 1. Domain Layer (`domain/`)
- `domain/models/skill.py`: Pure data models for `SkillDocument` and `SkillMatch`.
- `domain/models/scratchpad.py`: Pure data models for `ScratchpadReference` and buffer truncation settings.
- `domain/interfaces/skill.py`: `SkillRepositoryInterface` port for querying and loading skill runbooks.
- `domain/interfaces/scratchpad.py`: `ScratchpadStorageInterface` port for persisting massive tool outputs to disk/storage.
- `domain/interfaces/harness.py`: `AgentHarnessInterface` port for running bounded, guarded reasoning loops.

### 2. Application Layer (`application/`)
- `application/skills/matcher.py`: `SkillMatcherService` matching alert labels and annotations against domain skills.
- `application/harness/buffer.py`: `SmartOutputBufferService` performing head+tail truncation and triggering offloading through `ScratchpadStorageInterface`.
- `application/skills/`: Markdown skill documents for Kubernetes crashloops, PVC issues, and ArgoCD sync failures.
- Integrate `SkillMatcherService` into `DiagnoseIncidentUseCase` and `run_supervised`.

### 3. Infrastructure Layer (`infrastructure/`)
- `infrastructure/storage/scratchpad_file_storage.py`: Implements `ScratchpadStorageInterface` writing large payloads to `.lyoko/scratchpad/`.
- `infrastructure/skills/markdown_skill_repository.py`: Implements `SkillRepositoryInterface` discovering and loading `.md` runbooks.
- `infrastructure/llm/harness_runner.py`: Class-based ReAct loop runner (`ReActHarnessRunner`) implementing bounded execution with `SmartOutputBufferService`.
- Wire `OpenAILLMAdapter` and composition root to use the new runner.

### 4. Tests
- Unit tests for `SkillMatcherService` and markdown repository.
- Unit tests for `SmartOutputBufferService` (head+tail limits and scratchpad offloading).
- Unit tests for `ReActHarnessRunner` (repeat prevention, budget limits, status reporting).
- Integration test with `DiagnoseIncidentUseCase` and verify Clean Architecture test suite.

---

## Task Breakdown

- [ ] Task 1: Domain Entities & Interfaces
  - Create `domain/models/skill.py`
  - Create `domain/models/scratchpad.py`
  - Create `domain/interfaces/skill.py`
  - Create `domain/interfaces/scratchpad.py`
  - Create `domain/interfaces/harness.py`
  - Verify empty `__init__.py` files and Clean Architecture rules

- [ ] Task 2: Infrastructure Adapters (Storage & Skills Repository)
  - Create `infrastructure/storage/scratchpad_file_storage.py`
  - Create `infrastructure/skills/markdown_skill_repository.py`
  - Add initial skill runbooks under `application/skills/`
  - Write unit tests in `tests/agents/lyoko/test_scratchpad_storage.py` and `tests/agents/lyoko/test_skill_repository.py`

- [ ] Task 3: Application Services (SkillMatcherService & SmartOutputBufferService)
  - Create `application/skills/matcher.py`
  - Create `application/harness/buffer.py`
  - Write unit tests in `tests/agents/lyoko/test_skill_matcher.py` and `tests/agents/lyoko/test_output_buffer.py`

- [ ] Task 4: Infrastructure Harness Runner (Class-based ReAct Tool Loop)
  - Create `infrastructure/llm/harness_runner.py` (replacing procedural functions in `tool_loop.py` with an object-oriented class)
  - Refactor `infrastructure/llm/tool_loop.py` to delegate to `ReActHarnessRunner` for backwards compatibility
  - Wire `OpenAILLMAdapter` to inject `ReActHarnessRunner` and `SmartOutputBufferService`
  - Write unit tests in `tests/agents/lyoko/test_harness_runner.py`

- [ ] Task 5: Integration with Incident Diagnosis & Composition Root
  - Wire `SkillMatcherService` into `DiagnoseIncidentUseCase`
  - Update `composition.py` to instantiate and inject the storage, repository, matcher, and harness services
  - Run full test suite and verify `test_clean_architecture.py`
