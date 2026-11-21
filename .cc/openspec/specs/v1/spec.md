# v1: chat_turn with memory across executions

## Purpose
v1 shows the simplest Conductor conversational agent: one workflow per chat turn, memory carried from the previous execution, driven from a terminal client.

## Requirements

### Requirement: Memory across executions
The system SHALL load the history of the previous completed execution of the same session and use it in the next turn.

#### Scenario: v1: remembers facts from an earlier turn
- **WHEN** the user says "I am 55 and plan to retire at 62" and then asks "How many years until I retire?" in a chained turn
- **THEN** the second reply says 7 years and the output shows restored true with 4 history messages

### Requirement: Fresh start on bad pointer
The system SHALL start a fresh conversation when prevExecutionId is missing, unknown, or from another session.

#### Scenario: v1: foreign or missing previous execution starts fresh
- **WHEN** the user sends a turn with a random prevExecutionId or one from another session
- **THEN** the turn completes with restored false and a history of exactly 2 messages

### Requirement: Bounded history
The system SHALL keep at most 20 history messages, always starting with a user message.

#### Scenario: v1: 25 turns are trimmed to 20 messages
- **WHEN** the user chains 25 turns in one session
- **THEN** the final output history has 20 messages, the first with role user, roles alternating

### Requirement: Session traceability
The system SHALL start every turn with correlationId equal to sessionId and print links to each execution and the session search.

#### Scenario: v1: correlation search lists every turn
- **WHEN** the user runs 3 turns in one session
- **THEN** searching Conductor by that correlationId lists all 3 executions of convo_v1_chat_turn

#### Scenario: v1: chat client prints execution and session links and resumes
- **WHEN** the user chats via python -m v1.chat and later restarts it with --resume
- **THEN** each reply is followed by an execution link, a session link is shown, and the resumed turn reports memory restored

### Requirement: Provider swap by input
The system SHALL take llmProvider and model as workflow inputs with defaults, so changing them needs no workflow edit.

#### Scenario: v1: model override via input only
- **WHEN** the user runs a turn passing a different model input
- **THEN** the run completes using that model and the registered workflow definition is unchanged

### Requirement: Smoke and manifest
The system SHALL ship a manifest with no long-running processes and a smoke command that exits 0 after a real two-turn check.

#### Scenario: v1: smoke passes against the running stack
- **WHEN** the user runs python -m v1.smoke after ./convo.sh start v1
- **THEN** it prints the execution links and exits 0
