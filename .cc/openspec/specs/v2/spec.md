# v2: web chat page + gateway front door

## Purpose
v2 puts the chat in a browser: a static page talks to a local front door (stand-in for the Orkes API Gateway) that runs `convo_v2_chat_turn` synchronously, with resume, links into Conductor, and a reusable server other versions start with --version.

## Requirements

### Requirement: Front door API
The system SHALL serve /healthz, /api/config, /api/chat and /api/session, running the version's workflows synchronously and mapping failures to HTTP 400/502/504.

#### Scenario: v2: health and config report the version
- **WHEN** the user opens /healthz and /api/config on port 8720
- **THEN** they see ok true and a config naming version v2 with its title, features, flavor, provider and model

#### Scenario: v2: chat turn returns reply with links and steps
- **WHEN** the user posts a valid message to /api/chat
- **THEN** the response holds reply, history, executionId, uiUrl, sessionUrl and a steps list

#### Scenario: v2: bad request is rejected with 400
- **WHEN** the user posts a body with an empty message or missing sessionId
- **THEN** the response is HTTP 400 with an error text

#### Scenario: v2: failed workflow maps to 502 and slow workflow to 504
- **WHEN** the workflow fails, Conductor is unreachable, or the run is still RUNNING after the wait
- **THEN** the response is 502 with the reason (and executionId when known) or 504 with the executionId

#### Scenario: v2: session endpoint returns stored history
- **WHEN** the user calls /api/session with a sessionId and executionId
- **THEN** the response is the chat_history output with found and history

### Requirement: Reusable by other versions
The system SHALL let another version start the same server with --version and --static-dir, proxying to that version's workflows and overriding page files one by one.

#### Scenario: v2: another version reuses the front door
- **WHEN** the server is started with --version v3 and a static dir overriding only starters.json
- **THEN** chat calls run convo_v3_chat_turn, config reports v3, and the page uses v3 starters with v2's other files

### Requirement: Chat page behaviour
The system SHALL show a typing state, disable Send while a turn is in flight, store the pointer only on success, and offer resume and new chat.

#### Scenario: v2: typing state while a turn is in flight
- **WHEN** the user sends a message
- **THEN** the typing indicator shows and Send is disabled until the reply arrives

#### Scenario: v2: failed turn keeps the old pointer and offers Retry
- **WHEN** a turn fails
- **THEN** an error message with Retry appears and the stored executionId is unchanged

#### Scenario: v2: resume a previous chat
- **WHEN** the user reloads the page after a successful turn and clicks Continue
- **THEN** the banner "You left off here. Continue?" disappears and the earlier messages are shown again

#### Scenario: v2: new chat starts fresh
- **WHEN** the user clicks New chat
- **THEN** messages clear, starters show, and the next turn uses a new sessionId with an empty pointer

#### Scenario: v2: each reply shows links and what Conductor did
- **WHEN** a reply arrives
- **THEN** execution and session links appear and a steps panel lists each task with its type and time

#### Scenario: v2: starter prompt and model picker
- **WHEN** the user picks another model and clicks a starter prompt
- **THEN** the starter text is sent and the request carries the chosen model

### Requirement: Real chat with memory and resume
The system SHALL run real turns through Conductor, remember earlier turns, and refuse to resume another session's execution.

#### Scenario: v2: smoke passes against the running stack
- **WHEN** the user runs python -m v2.smoke after ./convo.sh start v2
- **THEN** the second turn answers 7 years, the session shows 4 history messages, and it exits 0

#### Scenario: v2: foreign session cannot be resumed
- **WHEN** the user asks /api/session for an execution with a different sessionId
- **THEN** the response has found false and an empty history

### Requirement: Orkes API Gateway setup
The system SHALL ship the API Gateway service definition and a setup script that explains the local stand-in on OSS.

#### Scenario: v2: gateway setup on OSS prints the stand-in notice
- **WHEN** the user runs python -m v2.gateway.setup_gateway --dry-run
- **THEN** it prints the wealth-advisor service definition with routes /chat and /session and the stand-in notice, and exits 0
