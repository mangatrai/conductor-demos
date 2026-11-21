# v3: the chat does real work (portfolio lookup)

## Purpose
v3 adds a portfolio lookup inside the chat turn: a router LLM with JSON output, a Switch, and a Sub Workflow that calls a local mock portfolio API over an HTTP task, so the bot answers with data it could not know.

## Requirements

### Requirement: Portfolio answers use real lookup data
The system SHALL answer a client portfolio question with numbers returned by the mock portfolio API via a visible sub-workflow.

#### Scenario: v3: portfolio question answers with mock numbers
- **WHEN** the user asks "What's in Jane Doe's portfolio?" in a v3 chat turn
- **THEN** the turn completes, the reply mentions Jane Doe's total value from the mock data, and the output lookup names a sub-workflow execution of convo_v3_get_portfolio

### Requirement: Plain chat makes no lookup
The system SHALL not run the portfolio sub-workflow for questions that are not about a client portfolio.

#### Scenario: v3: plain question triggers no lookup
- **WHEN** the user asks "What is a Roth IRA?" in a v3 chat turn
- **THEN** the turn completes with lookup null and no convo_v3_get_portfolio execution is started

### Requirement: Lookup stays out of history
The system SHALL inject lookup data only into the current turn's system message, never into the saved history.

#### Scenario: v3: history holds only user and assistant messages after a lookup
- **WHEN** the user asks about Jane Doe's portfolio
- **THEN** the output history has exactly the user message and the assistant reply, with no lookup JSON in it

### Requirement: Graceful lookup failures
The system SHALL complete the turn with a helpful reply when the client is unknown or the mock API is unavailable.

#### Scenario: v3: unknown client gets a not-found reply
- **WHEN** the user asks for the portfolio of a client not in the mock data
- **THEN** the turn completes, lookup.found is false, and the reply says the client was not found

#### Scenario: v3: mock API down still completes the turn
- **WHEN** the mock API returns errors and the user asks about Jane Doe's portfolio
- **THEN** the turn completes with lookup.error set and the reply says the data is unavailable

### Requirement: Standalone portfolio workflow and mock API
The system SHALL serve fictional portfolios on port 8731 and expose convo_v3_get_portfolio as its own workflow.

#### Scenario: v3: get_portfolio workflow returns holdings
- **WHEN** the user runs convo_v3_get_portfolio with clientName "Jane Doe"
- **THEN** it completes with found true and the mock holdings and total value

### Requirement: Web chat with lookup card
The system SHALL serve the v3 chat page on port 8730 that shows a lookup card linking to the sub-workflow execution.

#### Scenario: v3: web chat returns lookup extra and serves the card page
- **WHEN** the user posts a Jane Doe portfolio question to http://localhost:8730/api/chat
- **THEN** the response contains lookup with subWorkflowId and uiUrl, and GET / returns the page containing the looked-up card markup
