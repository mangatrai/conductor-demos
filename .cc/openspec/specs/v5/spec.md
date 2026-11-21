# v5: same bot as a Conductor Agent (code path)

## Purpose
Show the wealth-advisor bot built in a few lines of Python with the Conductor Agents SDK, running on the local Ollama model. It remembers a conversation across separate runs, is callable from a workflow through an AGENT task, and every run shows as a Conductor execution. Where the server lacks a feature, a reported fallback takes its place.

## Requirements

### Requirement: Agent remembers across runs
The system SHALL let a user run the `wealth_advisor` agent twice with the same session id and have the second run answer from the first, with both runs visible as Conductor executions.

#### Scenario: v5: second run remembers the first
- **WHEN** the user runs `python -m v5.chat --session S "My client is 55, retiring at 62"` and then `python -m v5.chat --session S "How many years left?"`
- **THEN** the second reply says 7 years, its output shows restored true, and both executions are found in Conductor under correlation id S

### Requirement: Memory is never lost silently
The system SHALL report where the conversation history came from (`memorySource`) and SHALL start fresh, with restored false and a reason, when the given previous execution is missing or belongs to another session.

#### Scenario: v5: foreign previous execution starts fresh and says so
- **WHEN** the user runs a turn for session B passing a previous execution id that belongs to session A
- **THEN** the output shows restored false, memorySource "none", and a memoryNote naming the reason

### Requirement: Agent callable from a workflow
The system SHALL register workflow `convo_v5_agent_turn` that runs the agent (AGENT task, or the reported local fallback) and returns the reply, history, executionId and agentMode.

#### Scenario: v5: workflow runs the agent
- **WHEN** the user starts `convo_v5_agent_turn` with a sessionId and the message "Hello, what can you help me with?"
- **THEN** the execution completes with a non-empty reply and agentMode "server" or "local"

### Requirement: Portfolio tool
The system SHALL give the agent a `get_portfolio` tool backed by v5's own mock data.

#### Scenario: v5: agent looks up a portfolio
- **WHEN** the user asks the agent "What's in Jane Doe's portfolio?"
- **THEN** the reply contains Jane Doe's holdings from the mock data and the output lists a get_portfolio tool call

### Requirement: Web chat front door
The system SHALL serve the v5 chat on port 8750 through the shared web front door, with chat_turn output that matches the S4 contract.

#### Scenario: v5: chat in the browser API remembers
- **WHEN** the user posts "My client is 55, retiring at 62" and then "How many years left?" to http://localhost:8750/api/chat with the same sessionId and the returned executionId
- **THEN** the second response says 7 years, shows restored true, and carries a uiUrl to the execution

### Requirement: Runnable version with smoke and probe
The system SHALL provide `v5/manifest.json` so the launcher can start, list and smoke v5, a probe that reports which server features work, and offline tests.

#### Scenario: v5: launcher smoke passes
- **WHEN** the user runs `./convo.sh start v5` and then `./convo.sh smoke v5`
- **THEN** smoke exits 0 and prints the memorySource and agentMode it used

#### Scenario: v5: probe reports server features
- **WHEN** the user runs `python -m v5.probe`
- **THEN** it prints JSON with aiEnabled, agentTask and sdkSessionMemory, each true or false
