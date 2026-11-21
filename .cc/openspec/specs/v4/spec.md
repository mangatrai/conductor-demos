# v4: same workflows as MCP tools

## Purpose
Expose the wealth-advisor chat turn and the portfolio lookup, running as Conductor workflows, as MCP tools that Claude Desktop or any MCP client can call, with every call visible as an execution in Conductor.

## Requirements

### Requirement: MCP tool catalogue
The system SHALL serve an MCP server on Streamable HTTP at port 8740 and on stdio listing the tools `ask_wealth_advisor` and `get_portfolio` with input schemas that mirror the workflow inputs.

#### Scenario: v4: tools are listed
- **WHEN** an MCP client connects to http://localhost:8740/mcp and lists tools
- **THEN** it sees `ask_wealth_advisor` with a required `message` and `get_portfolio` with a required `clientName`

### Requirement: Portfolio tool runs the workflow
The system SHALL run `convo_v4_get_portfolio` for each `get_portfolio` call and return the portfolio data with the execution link.

#### Scenario: v4: portfolio lookup through MCP
- **WHEN** an MCP client calls `get_portfolio` with clientName "Jane Doe"
- **THEN** the result contains Jane Doe's holdings and an execution link, and that execution is COMPLETED in Conductor

### Requirement: Chat tool keeps the conversation
The system SHALL run `convo_v4_chat_turn` for each `ask_wealth_advisor` call, keeping the session pointers per MCP session unless the caller passes them, and return the reply with the execution link.

#### Scenario: v4: second question remembers the first
- **WHEN** an MCP client calls `ask_wealth_advisor` twice in one MCP session, the second asking about the first
- **THEN** both results carry the same sessionId and an execution link, the second shows restored true, and both executions are found in Conductor under that sessionId

### Requirement: Failures are reported, not hidden
The system SHALL return an MCP error result naming the reason when the workflow fails or Conductor is unreachable.

#### Scenario: v4: Conductor down gives a tool error
- **WHEN** a tool is called while Conductor cannot be reached
- **THEN** the client receives an error result saying Conductor is unreachable instead of a crash

### Requirement: Runnable alongside other versions
The system SHALL start v4 with the launcher and provide a Claude Desktop config and an Orkes MCP Gateway setup.

#### Scenario: v4: launcher starts v4 and smoke passes
- **WHEN** the user runs `./convo.sh start v4` and then `./convo.sh smoke v4`
- **THEN** status shows the MCP server and mock healthy and the smoke exits 0

#### Scenario: v4: Claude Desktop config is ready to paste
- **WHEN** the user opens `convo-agent/v4/claude_desktop/`
- **THEN** they find valid JSON configs for stdio and for mcp-remote to the HTTP endpoint, and a gateway setup doc
