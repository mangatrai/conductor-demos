# platform

## Purpose
Shared base for all convo-agent versions: config, Conductor client, registrar, LLM fallback worker, Step-0 checks, launcher and hub.

## Requirements

### Requirement: Launcher lists versions
The system SHALL list every version found in v*/manifest.json with its title and features.

#### Scenario: platform: list versions
- **WHEN** the user runs `./convo.sh list`
- **THEN** each version id, title and features are printed and the exit code is 0

#### Scenario: platform: unknown version rejected
- **WHEN** the user runs `./convo.sh start v9`
- **THEN** an error naming v9 is printed and the exit code is non-zero

#### Scenario: platform: status table
- **WHEN** the user runs `./convo.sh status all`
- **THEN** one row per version process with its port and health is printed and the exit code is 0

### Requirement: Step-0 platform checks
The system SHALL probe Conductor and Ollama once and record whether native LLM_CHAT_COMPLETE works, how GET_WORKFLOW reads behave, and how a Switch branch that was not taken resolves, choosing the LLM mode from the result.

#### Scenario: platform: step-0 report
- **WHEN** the user runs `./convo.sh checks` with Conductor running
- **THEN** `.run/checks.json` lists the llm_native, get_workflow, get_workflow_missing and switch_not_taken results and `.run/llm_mode` holds native or worker

### Requirement: Registrar rewrites LLM tasks
The system SHALL replace placeholders and, in worker mode, rewrite LLM_CHAT_COMPLETE tasks into convo_llm_chat SIMPLE tasks.

#### Scenario: platform: worker rewrite
- **WHEN** a workflow with an LLM_CHAT_COMPLETE task and {{LLM_MODEL}} is prepared in worker mode
- **THEN** the task becomes SIMPLE convo_llm_chat with the same taskReferenceName and inputParameters and the model placeholder is replaced

### Requirement: Config loading order
The system SHALL read convo-agent/.env, then the repo .env, never overriding real environment variables.

#### Scenario: platform: env precedence
- **WHEN** a key is set in the environment and in both .env files
- **THEN** the environment value wins, then convo-agent/.env, then the repo .env

### Requirement: Hub lists versions
The system SHALL serve a hub on port 8700 listing each version with title, features, status and links.

#### Scenario: platform: hub versions api
- **WHEN** the hub is started and the user requests GET /api/versions
- **THEN** a JSON list with one entry per manifest including title, features and running status is returned

#### Scenario: platform: hub version tour
- **WHEN** the user opens the hub page at /
- **THEN** the page contains a "Version tour" section comparing the features of each version

### Requirement: Fallback LLM worker
The system SHALL answer convo_llm_chat tasks from Ollama, parsing JSON when jsonOutput is true.

#### Scenario: platform: worker json output
- **WHEN** the worker handles a task with jsonOutput true and the model returns JSON text
- **THEN** the output result is the parsed JSON object, and the raw string when it cannot parse
